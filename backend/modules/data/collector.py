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
    SchemaValidationError,
)
from backend.models.data_catalogue import DataCatalogueItem
from backend.models.data_source import DataSource
from backend.plugins import config_with_env_keys
from backend.plugins.base import get_plugin
from .country_utils import CountryMatcher

logger = logging.getLogger(__name__)

#: Per-item wall-clock budget for the retry loop, in seconds. Overridable
#: with ``BEACON_FETCH_RETRY_BUDGET_SECONDS``.
FETCH_RETRY_BUDGET_SECONDS = 120.0


def _fetch_retry_budget_seconds() -> float:
    """Resolve the per-item retry budget (env override, invalid values ignored).

    Attempt counts alone do not bound wall time: tenacity's three attempts
    compound with the HTTP layer's own retries (``ResilientSession``: up to
    four urllib3 retries with backoff, timeouts up to 30s each), so one
    catalogue item could otherwise spend minutes against a struggling
    provider while the beat tick enqueues every five. The budget bounds the
    *between-attempt* window only -- tenacity evaluates stop conditions
    after an attempt completes, so a legitimately long single fetch (ECB
    paging, for instance) is never cut off mid-flight; it is further
    retries, past the budget, that stop.
    """
    raw = os.getenv("BEACON_FETCH_RETRY_BUDGET_SECONDS")
    if raw is None or not str(raw).strip():
        return FETCH_RETRY_BUDGET_SECONDS
    try:
        return max(float(raw), 0.0)
    except ValueError:
        logger.warning(
            "BEACON_FETCH_RETRY_BUDGET_SECONDS=%r is not a number; using %.0fs",
            raw,
            FETCH_RETRY_BUDGET_SECONDS,
        )
        return FETCH_RETRY_BUDGET_SECONDS


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
                df = self._fetch_with_retry(item, start_date, end_date)
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

    # Transient provider outages (network blips, rate windows, 5xx) are
    # retried with bounded exponential backoff; every other typed failure
    # (missing dataset, schema violation, restricted source) is a decision,
    # not a blip, and is raised on the first attempt. tenacity is a declared
    # dependency that nothing used until the sixth round. The retry loop is
    # bounded twice: by attempts (3) and by wall clock
    # (_fetch_retry_budget_seconds), because the HTTP layer beneath retries
    # too and attempt counts alone do not bound the time one item can spend
    # against a struggling provider (pipeline-review finding F8).
    def _fetch_with_retry(self, item, start_date, end_date):
        from tenacity import (
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            stop_after_delay,
            wait_exponential_jitter,
        )

        from backend.exceptions import DataSourceUnavailableError

        @retry(
            retry=retry_if_exception_type(DataSourceUnavailableError),
            stop=stop_after_attempt(3) | stop_after_delay(_fetch_retry_budget_seconds()),
            wait=wait_exponential_jitter(initial=1, max=8),
            reraise=True,
        )
        def _attempt():
            return self._fetch_item_data(item, start_date, end_date)

        return _attempt()

    def _fetch_item_data(self, item: DataCatalogueItem, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch data for a single catalogue item using the plugin system."""
        data_source = item.data_source
        if not data_source:
            raise DataIngestionError(
                f"No data source configured for catalogue item '{item.code}'",
                context={"code": item.code, "item_id": item.id},
            )

        plugin_type = data_source.plugin_type
        plugin_class = get_plugin(plugin_type)
        if not plugin_class:
            raise DataSourceUnavailableError(
                f"Plugin type '{plugin_type}' is not registered",
                context={"code": item.code, "plugin_type": plugin_type},
            )

        # API keys live in the environment rather than the database so they are
        # never returned by the configuration endpoints; the registry owns the
        # plugin->env-var map so the probe route injects identically.
        config = config_with_env_keys(plugin_type, data_source.config)

        plugin = plugin_class(config)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        endpoint = item.endpoint if item.endpoint else item.code

        # Catalogue categories describe the economic meaning of a series, not
        # the transport shape returned by its provider.  FRED publishes bond
        # yields and commodity benchmarks as indicator series, so routing all
        # ``bonds``/``commodities`` items to ``fetch_asset_data`` makes valid
        # FRED IDs fail with its intentional "does not support asset price
        # data" response.  Keep the category fallback for true market-price
        # providers while allowing a catalogue item to opt into indicator
        # mode explicitly.
        configured_data_type = (getattr(item, "parameters", None) or {}).get("data_type")
        indicator_plugins = {
            "fred",
            "sec_edgar",
            "world_bank",
            "bis",
            "imf",
            "ai4risk_interbank",
        }
        is_indicator = configured_data_type == "indicator" or plugin_type in indicator_plugins

        if not is_indicator and item.category in ['exchange_rates', 'stocks', 'bonds', 'commodities']:
            df = plugin.fetch_asset_data([endpoint], start_dt, end_dt)
        else:
            df = plugin.fetch_indicator_data(endpoint, start_dt, end_dt)

        if df is None:
            raise EmptyDatasetError(
                f"Plugin '{data_source.plugin_type}' returned no data for '{endpoint}'",
                context={"code": item.code, "endpoint": endpoint},
            )

        # The plugin contract is canonical ``Date``/``Value`` (or ``Close``
        # for assets), but several public statistical APIs naturally expose
        # lowercase ``date``/``value``. Normalize those names at the collector
        # boundary so the validator and quality gate see the same schema for
        # every provider; this does not alter values or add observations.
        frame = df.copy()
        for canonical in ("Date", "Value", "Close"):
            if canonical in frame.columns:
                continue
            match = next(
                (column for column in frame.columns if str(column).lower() == canonical.lower()),
                None,
            )
            if match is not None:
                frame = frame.rename(columns={match: canonical})

        # Providers occasionally return a small amount of padding around a
        # requested window (the ECB fallback did this for four exchange-rate
        # series).  The collector owns the requested-window contract, so clip
        # only after schema normalisation and never let an out-of-window row
        # enter validation, feature engineering, or the certified snapshot.
        date_column = next(
            (column for column in ("Date", "date", "timestamp", "time") if column in frame.columns),
            None,
        )
        if date_column is not None:
            parsed_dates = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
            if parsed_dates.isna().any():
                invalid = int(parsed_dates.isna().sum())
                raise SchemaValidationError(
                    f"Provider returned {invalid} unparseable date(s) for '{item.code}'",
                    context={"code": item.code, "date_column": date_column, "invalid_dates": invalid},
                )
            parsed_dates = parsed_dates.dt.tz_localize(None)
            start_ts = pd.Timestamp(start_dt)
            end_ts = pd.Timestamp(end_dt)
            in_window = (parsed_dates >= start_ts) & (parsed_dates <= end_ts)
            clipped = int((~in_window).sum())
            if clipped:
                logger.info(
                    "[%s] Clipped %d out-of-window row(s) from %s (%s..%s)",
                    self.job_id,
                    clipped,
                    item.code,
                    start_date,
                    end_date,
                )
            frame = frame.loc[in_window].copy()
            frame[date_column] = parsed_dates.loc[in_window].to_numpy()
            if frame.empty:
                raise EmptyDatasetError(
                    f"Source returned no rows for '{item.code}' inside the requested window",
                    context={
                        "code": item.code,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )

        return frame
