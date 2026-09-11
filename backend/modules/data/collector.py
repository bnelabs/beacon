"""Data Collector - Multi-source data collection."""

import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.exceptions import (
    BeaconError,
    DataIngestionError,
    DataQualityError,
    DataSourceUnavailableError,
    EmptyDatasetError,
)
from backend.models.data_catalogue import DataCatalogueItem
from backend.models.data_source import DataSource
from backend.plugins.base import get_plugin
from .country_utils import CountryMatcher

logger = logging.getLogger(__name__)


@dataclass
class CollectionFailure:
    """A single catalogue item that could not be collected."""

    code: str
    plugin_type: str
    error_code: str
    message: str
    severity: str = "error"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class CollectionReport:
    """Per-run outcome of a collection attempt."""

    requested: int = 0
    collected: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    failures: List[CollectionFailure] = field(default_factory=list)

    @property
    def failed(self) -> List[str]:
        return [failure.code for failure in self.failures]

    @property
    def success_ratio(self) -> float:
        attempted = len(self.collected) + len(self.failures)
        if attempted == 0:
            return 0.0
        return len(self.collected) / attempted

    def to_dict(self) -> Dict[str, object]:
        return {
            "requested": self.requested,
            "collected": list(self.collected),
            "skipped": list(self.skipped),
            "failed": self.failed,
            "success_ratio": self.success_ratio,
            "failures": [failure.to_dict() for failure in self.failures],
        }


class DataCollector:
    """Collects data from multiple sources based on catalogue selection."""

    def __init__(self, db: Session, job_id: str, output_dir: str):
        self.db = db
        self.job_id = job_id
        self.output_dir = output_dir
        self.last_report: Optional[CollectionReport] = None

    def collect(
        self,
        catalogue_items: List[int],
        start_date: str,
        end_date: str,
        country_filters: Optional[List[str]] = None,
        region_filters: Optional[List[str]] = None,
        fail_on_any_error: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """Collect every selected catalogue item.

        Individual source failures are recorded in :attr:`last_report` rather
        than being flattened into empty frames. The run aborts when *nothing*
        could be collected, and -- by default -- when *any* selected item failed.

        Strict is the default on purpose: this is a risk engine, and a systemic
        risk score computed over a silently partial panel is worse than no score
        at all. Partial collection is available, but only as an explicit
        ``fail_on_any_error=False`` opt-out at the call site.

        Raises:
            DataIngestionError: No catalogue item produced usable data.
            DataQualityError: Some items failed and strict mode is in force.
            ValueError: Active country filters matched no catalogue item.
        """
        logger.info("[%s] Collecting %d datasets", self.job_id, len(catalogue_items))

        report = CollectionReport(requested=len(catalogue_items))
        collected: Dict[str, pd.DataFrame] = {}
        matcher = CountryMatcher(country_filters, region_filters)

        for item_id in catalogue_items:
            item = self.db.query(DataCatalogueItem).filter(DataCatalogueItem.id == item_id).first()
            if not item:
                logger.warning("Catalogue item %s not found", item_id)
                report.skipped.append(str(item_id))
                continue

            if not matcher.should_collect(item):
                logger.info(
                    "[%s] Skipping %s (%s) - outside selected country scope '%s'",
                    self.job_id,
                    item.code,
                    getattr(item, "region", None),
                    matcher.describe(),
                )
                report.skipped.append(item.code)
                continue

            plugin_type = getattr(item.data_source, "plugin_type", "unknown") if item.data_source else "unknown"
            try:
                df = self._fetch_item_data(item, start_date, end_date)
                if df is None or df.empty:
                    raise EmptyDatasetError(
                        f"Source returned no rows for '{item.code}'",
                        context={"code": item.code, "plugin_type": plugin_type},
                    )
                collected[item.code] = df
                report.collected.append(item.code)
                logger.info("Collected %d records for %s", len(df), item.code)
            except BeaconError as exc:
                report.failures.append(
                    CollectionFailure(
                        code=item.code,
                        plugin_type=plugin_type,
                        error_code=exc.code,
                        message=str(exc),
                        severity=exc.severity,
                    )
                )
                logger.error("[%s] Failed to collect %s (%s): %s", self.job_id, item.code, exc.code, exc)
            except Exception as exc:  # noqa: BLE001 - unexpected provider errors still need a code
                report.failures.append(
                    CollectionFailure(
                        code=item.code,
                        plugin_type=plugin_type,
                        error_code="DATA_INGESTION_FAILED",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
                logger.exception("[%s] Failed to collect %s", self.job_id, item.code)

        self.last_report = report

        if matcher.active and not report.collected:
            raise ValueError("Selected country filters did not match any catalogue data sets.")

        if not collected:
            if report.requested == 0:
                raise DataIngestionError(
                    "No catalogue items were requested",
                    context={"job_id": self.job_id},
                )
            if not report.failures:
                raise DataIngestionError(
                    "No catalogue items produced data; every item was skipped or unmatched",
                    context={"job_id": self.job_id, "skipped": report.skipped},
                )
            raise DataIngestionError(
                "Every selected data source failed; refusing to continue with an empty payload",
                context={"job_id": self.job_id, "failures": [f.to_dict() for f in report.failures]},
            )

        if fail_on_any_error and report.failures:
            first_failure = report.failures[0]
            raise DataQualityError(
                "Strict collection is the default and some data sources failed: "
                f"{first_failure.code} ({first_failure.error_code})",
                context={
                    "job_id": self.job_id,
                    "collected": list(report.collected),
                    "success_ratio": report.success_ratio,
                    "failures": [f.to_dict() for f in report.failures],
                    "opt_out": "pass fail_on_any_error=False to accept a partial panel",
                },
            )

        if report.failures:
            logger.warning(
                "[%s] Collection completed with %d/%d sources failing (success ratio %.2f)",
                self.job_id,
                len(report.failures),
                len(report.collected) + len(report.failures),
                report.success_ratio,
            )

        return collected

    def _fetch_item_data(self, item: DataCatalogueItem, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch data for a single catalogue item using the plugin system."""
        data_source = item.data_source
        if not data_source:
            raise DataIngestionError(
                f"No data source configured for catalogue item '{item.code}'",
                context={"code": item.code, "item_id": item.id},
            )

        plugin_class = get_plugin(data_source.plugin_type)
        if not plugin_class:
            raise DataSourceUnavailableError(
                f"Plugin type '{data_source.plugin_type}' is not registered",
                context={"code": item.code, "plugin_type": data_source.plugin_type},
            )

        config = dict(data_source.config or {})

        # API keys live in the environment rather than the database so they are
        # never returned by the configuration endpoints.
        env_keys = {
            'fred': 'FRED_API_KEY',
            'alpha_vantage': 'ALPHA_VANTAGE_API_KEY',
            'sec_edgar': 'SEC_API_KEY',
        }
        env_var = env_keys.get(data_source.plugin_type)
        if env_var and not config.get('api_key'):
            value = os.getenv(env_var)
            if value:
                config['api_key'] = value
                logger.info("Injected %s API key from environment", data_source.plugin_type)

        plugin = plugin_class(config)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        endpoint = item.endpoint if item.endpoint else item.code

        if item.category in ['exchange_rates', 'stocks', 'bonds', 'commodities']:
            df = plugin.fetch_asset_data([endpoint], start_dt, end_dt)
        else:
            df = plugin.fetch_indicator_data(endpoint, start_dt, end_dt)

        if df is None:
            raise EmptyDatasetError(
                f"Plugin '{data_source.plugin_type}' returned no data for '{endpoint}'",
                context={"code": item.code, "endpoint": endpoint},
            )

        return df
