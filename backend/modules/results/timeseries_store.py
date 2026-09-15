"""Read/write access to the time-series tables.

The dashboards need two things from this store: durable writes as data streams
in, and cheap time-window aggregations on the way out. On TimescaleDB the
aggregations are served by the ``risk_scores_daily`` continuous aggregate; on
plain PostgreSQL or SQLite the store transparently falls back to a ``GROUP BY``
over the base table. The fallback is slower but returns the same shape of
answer, and every result records which path produced it so an operator can tell
whether the pre-aggregates are actually being used.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.models.timeseries import (
    IndicatorObservation,
    IndicatorVintageLog,
    ModelMetricPoint,
    RiskScorePoint,
)

logger = logging.getLogger(__name__)

RISK_SCORES_DAILY = "risk_scores_daily"
INDICATOR_OBSERVATIONS_DAILY = "indicator_observations_daily"

BASE_TABLE_SOURCE = "base_table"
CONTINUOUS_AGGREGATE_SOURCE = "continuous_aggregate"

_RISK_SCORE_KEYS = ("time", "entity_type", "entity_id", "model_version", "horizon_days")
_OBSERVATION_KEYS = ("time", "source_code", "indicator_code", "region")
_METRIC_KEYS = ("time", "job_id", "metric_name")


@dataclass
class RegionRiskSummary:
    """Average liquidity risk for one region over a trailing window."""

    region: str
    days: int
    avg_risk_score: float
    max_risk_score: float
    observations: int
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TimeSeriesStore:
    """Time-series persistence and windowed aggregation."""

    def __init__(self, session: Session):
        self.session = session
        self._aggregate_cache: Dict[str, bool] = {}

    # -- capability probing -------------------------------------------------

    def has_continuous_aggregate(self, view_name: str) -> bool:
        """Return whether a TimescaleDB continuous aggregate exists."""
        if view_name in self._aggregate_cache:
            return self._aggregate_cache[view_name]

        if self.session.get_bind().dialect.name != "postgresql":
            self._aggregate_cache[view_name] = False
            return False

        try:
            found = self.session.execute(
                text(
                    "SELECT 1 FROM timescaledb_information.continuous_aggregates "
                    "WHERE view_name = :name"
                ),
                {"name": view_name},
            ).scalar()
            available = bool(found)
        except Exception:  # noqa: BLE001 - absence of the catalog view means no TimescaleDB
            self.session.rollback()
            available = False

        self._aggregate_cache[view_name] = available
        return available

    # -- writes -------------------------------------------------------------

    def record_observations(self, rows: Iterable[Dict[str, Any]]) -> int:
        """Upsert indicator observations keyed by (time, source, indicator, region).

        Every written row also appends to the vintage log: the latest-value
        store keeps what is currently believed, the log keeps what was
        believed when, which is the difference between a restated series and
        a silently rewritten history.
        """
        rows = list(rows)
        count = self._upsert(
            IndicatorObservation,
            rows,
            key_columns=list(_OBSERVATION_KEYS),
            update_columns=["country", "value", "unit", "quality_score", "ingest_job_id"],
        )
        self._append_vintages(rows)
        return count

    def _append_vintages(self, rows: Iterable[Dict[str, Any]]) -> None:
        from datetime import datetime, timezone

        published_at = datetime.now(timezone.utc)
        vintages = [
            IndicatorVintageLog(
                source_code=row["source_code"],
                indicator_code=row["indicator_code"],
                region=row.get("region") or "GLOBAL",
                time=row["time"],
                value=row["value"],
                published_at=published_at,
                ingest_job_id=row.get("ingest_job_id"),
            )
            for row in rows
        ]
        if vintages:
            self.session.add_all(vintages)
            self.session.commit()

    def observations_as_of(
        self,
        source_code: str,
        indicator_code: str,
        as_of,
        region: Optional[str] = None,
    ):
        """The series as it was believed at ``as_of``.

        For each period, the newest vintage published at or before ``as_of``:
        exactly the values a decision made at that instant could have seen.
        Restatements published later are invisible here by construction.
        """
        query = self.session.query(IndicatorVintageLog).filter(
            IndicatorVintageLog.source_code == source_code,
            IndicatorVintageLog.indicator_code == indicator_code,
            IndicatorVintageLog.published_at <= as_of,
        )
        if region:
            query = query.filter(IndicatorVintageLog.region == region)
        rows = query.order_by(
            IndicatorVintageLog.time, IndicatorVintageLog.published_at
        ).all()
        latest: Dict[Any, Any] = {}
        for row in rows:
            latest[row.time] = row
        return [latest[key] for key in sorted(latest)]

    def record_risk_scores(self, rows: Iterable[Dict[str, Any]]) -> int:
        """Upsert risk scores keyed by (time, entity_type, entity_id, model_version, horizon)."""
        return self._upsert(
            RiskScorePoint,
            list(rows),
            key_columns=list(_RISK_SCORE_KEYS),
            update_columns=["region", "country", "risk_score", "risk_level", "prediction_job_id"],
        )

    def record_model_metrics(self, rows: Iterable[Dict[str, Any]]) -> int:
        """Upsert model metrics keyed by (time, job_id, metric_name)."""
        return self._upsert(
            ModelMetricPoint,
            list(rows),
            key_columns=list(_METRIC_KEYS),
            update_columns=[
                "metric_value",
                "model_version",
                "model_type",
                "region",
                "horizon_days",
            ],
        )

    def _upsert(
        self,
        model: Any,
        rows: List[Dict[str, Any]],
        key_columns: Sequence[str],
        update_columns: Sequence[str],
    ) -> int:
        if not rows:
            return 0

        insert_factory = self._dialect_insert()
        if insert_factory is None:
            # Portable fallback for dialects without ON CONFLICT (e.g. Oracle).
            for row in rows:
                self.session.merge(model(**row))
            self.session.commit()
            return len(rows)

        statement = insert_factory(model).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=list(key_columns),
            set_={column: getattr(statement.excluded, column) for column in update_columns},
        )
        self.session.execute(statement)
        self.session.commit()
        return len(rows)

    def _dialect_insert(self):
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert

            return insert
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert

            return insert
        return None

    # -- reads --------------------------------------------------------------

    def average_risk_by_region(
        self,
        days: int = 30,
        *,
        end: Optional[datetime] = None,
        entity_type: Optional[str] = None,
    ) -> List[RegionRiskSummary]:
        """Average risk score per region over the trailing ``days`` window.

        Uses the ``risk_scores_daily`` continuous aggregate when TimescaleDB
        provides it, otherwise aggregates the base table directly.
        """
        if days <= 0:
            raise ValueError("days must be positive")

        end = end or datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        if self.has_continuous_aggregate(RISK_SCORES_DAILY):
            summaries = self._aggregate_from_continuous_view(start, end, days, entity_type)
            if summaries is not None:
                return summaries

        return self._aggregate_from_base_table(start, end, days, entity_type)

    def _aggregate_from_continuous_view(
        self,
        start: datetime,
        end: datetime,
        days: int,
        entity_type: Optional[str],
    ) -> Optional[List[RegionRiskSummary]]:
        query = (
            "SELECT region, "
            "       avg(avg_risk_score) AS avg_risk, "
            "       max(max_risk_score) AS max_risk, "
            "       sum(observation_count) AS observations "
            f"FROM {RISK_SCORES_DAILY} "
            "WHERE bucket >= :start AND bucket <= :end AND region IS NOT NULL "
        )
        params: Dict[str, Any] = {"start": start, "end": end}
        if entity_type:
            query += "AND entity_type = :entity_type "
            params["entity_type"] = entity_type
        query += "GROUP BY region ORDER BY avg_risk DESC"

        try:
            rows = self.session.execute(text(query), params).all()
        except Exception:  # noqa: BLE001 - fall back rather than fail the request
            logger.warning(
                "Continuous aggregate %s is present but not queryable; "
                "falling back to the base table",
                RISK_SCORES_DAILY,
                exc_info=True,
            )
            self.session.rollback()
            return None

        return [
            RegionRiskSummary(
                region=row[0],
                days=days,
                avg_risk_score=float(row[1] or 0.0),
                max_risk_score=float(row[2] or 0.0),
                observations=int(row[3] or 0),
                source=CONTINUOUS_AGGREGATE_SOURCE,
            )
            for row in rows
        ]

    def _aggregate_from_base_table(
        self,
        start: datetime,
        end: datetime,
        days: int,
        entity_type: Optional[str],
    ) -> List[RegionRiskSummary]:
        statement = (
            select(
                RiskScorePoint.region,
                func.avg(RiskScorePoint.risk_score),
                func.max(RiskScorePoint.risk_score),
                func.count(),
            )
            .where(
                RiskScorePoint.time >= start,
                RiskScorePoint.time <= end,
                RiskScorePoint.region.isnot(None),
            )
            .group_by(RiskScorePoint.region)
            .order_by(func.avg(RiskScorePoint.risk_score).desc())
        )
        if entity_type:
            statement = statement.where(RiskScorePoint.entity_type == entity_type)

        rows = self.session.execute(statement).all()
        return [
            RegionRiskSummary(
                region=row[0],
                days=days,
                avg_risk_score=float(row[1] or 0.0),
                max_risk_score=float(row[2] or 0.0),
                observations=int(row[3] or 0),
                source=BASE_TABLE_SOURCE,
            )
            for row in rows
        ]

    def latest_risk_scores(
        self,
        *,
        entity_type: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 100,
    ) -> List[RiskScorePoint]:
        """Return the most recent risk score rows, newest first."""
        statement = select(RiskScorePoint).order_by(RiskScorePoint.time.desc()).limit(limit)
        if entity_type:
            statement = statement.where(RiskScorePoint.entity_type == entity_type)
        if region:
            statement = statement.where(RiskScorePoint.region == region)
        return list(self.session.execute(statement).scalars().all())

    def metric_history(
        self,
        metric_name: str,
        *,
        days: int = 90,
        end: Optional[datetime] = None,
    ) -> List[ModelMetricPoint]:
        """Return one metric's points over the trailing window, oldest first."""
        end = end or datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        statement = (
            select(ModelMetricPoint)
            .where(
                ModelMetricPoint.metric_name == metric_name,
                ModelMetricPoint.time >= start,
                ModelMetricPoint.time <= end,
            )
            .order_by(ModelMetricPoint.time.asc())
        )
        return list(self.session.execute(statement).scalars().all())
