"""DATA Module Orchestrator - Coordinates collection, validation, and preparation."""

import logging
import os
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

import pandas as pd
from sqlalchemy.orm import Session

from backend.exceptions import DataQualityError
from backend.models.data_catalogue import DataCatalogueItem
from backend.models.data_source import DataSource
from .collector import DataCollector
from .validator import DataValidator
from .cleaner import DataCleaner
from .formatter import DataFormatter
from .analyzer import DataAnalyzer
from .monitor import DataMonitor
from .quality_gate import DataQualityGate, QualityAttestation, QualityComponents, QualityPolicy
from .snapshots import DatasetSnapshot, DatasetSnapshotter, snapshot_root_for

logger = logging.getLogger(__name__)


class DataStatus(str, Enum):
    """Data processing status."""
    PENDING = "pending"
    COLLECTING = "collecting"
    VALIDATING = "validating"
    CLEANING = "cleaning"
    FORMATTING = "formatting"
    ANALYZING = "analyzing"
    CERTIFIED = "certified"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class DataQualityReport:
    """Data quality assessment report.

    ``quality_score`` and ``fit_for_engine`` are filled in from the gate's
    attestation once the payload has been verified; the component sub-scores are
    the only numbers this report computes itself.
    """
    job_id: str
    quality_score: float  # 0-100
    completeness: float  # % non-null
    consistency: float  # % passes validation
    timeliness: float  # % recent data
    accuracy: Optional[float]  # % within expected ranges; None when unmeasured

    anomalies_detected: int
    anomalies_fixed: int
    warnings: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]

    fit_for_engine: bool
    recommendation: str

    components: QualityComponents

    timestamp: datetime


@dataclass
class DataPackage:
    """Prepared data package for ENGINE."""
    job_id: str
    timeseries_path: str
    features_path: str

    metadata: Dict[str, Any]
    quality_report: DataQualityReport

    date_range: tuple
    num_assets: int
    num_observations: int

    certified_at: datetime
    certified_by: str
    snapshot_id: Optional[str] = None


class DataOrchestrator:
    """
    Main orchestrator for DATA module.

    Coordinates: Collection → Validation → Cleaning → Formatting → Analysis → Certification
    """

    def __init__(self, db: Session, job_id: str, output_dir: str, progress_callback: Optional[Callable[[float, str], None]] = None):
        self.db = db
        self.job_id = job_id
        self.output_dir = output_dir
        self.progress_callback = progress_callback

        # Initialize components
        self.collector = DataCollector(db, job_id, output_dir)
        self.validator = DataValidator(job_id)
        self.cleaner = DataCleaner(job_id)
        self.formatter = DataFormatter(job_id)
        self.analyzer = DataAnalyzer(job_id)
        self.monitor = DataMonitor(db, job_id)

        self.quality_gate = DataQualityGate(
            QualityPolicy(),
            alert_sink=self._emit_data_quality_alert,
        )
        self.attestation: Optional[QualityAttestation] = None
        # Content-addressed copy of the exact rows the gate verified, so the
        # verdict can be re-checked (or proven irreproducible) later.
        self.snapshotter = DatasetSnapshotter(snapshot_root_for(output_dir))
        self.snapshot: Optional[DatasetSnapshot] = None

        self.status = DataStatus.PENDING
        self.current_step = None
        self.progress = 0.0

    def _emit_data_quality_alert(self, source_name: str, issue: str, severity: str) -> None:
        """Raise a data-quality notification so operators see ingestion problems."""
        from backend.services.notification_service import NotificationService

        NotificationService(self.db).create_data_quality_alert(source_name, issue, severity)

    def _update_progress(self, progress: float, message: str):
        """Update internal progress and call callback if provided."""
        self.progress = progress
        self.current_step = message
        self.monitor.update(self.status.value, self.progress, self.current_step)

        if self.progress_callback:
            self.progress_callback(progress, message)

    def run(
        self,
        catalogue_items: List[int],
        start_date: str,
        end_date: str,
        user_id: str,
        countries: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        fail_on_any_error: bool = True,
    ) -> DataPackage:
        """
        Execute complete DATA pipeline.

        Args:
            catalogue_items: List of catalogue item IDs to collect
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            user_id: User who initiated
            countries: Optional list of country names for filtering
            regions: Optional list of region codes from UI
            fail_on_any_error: Whether one failed item should fail the whole
                collection. Strict mode remains the default; an explicit
                false value records provider failures and continues with the
                usable panel.

        Returns:
            DataPackage ready for ENGINE
        """
        try:
            logger.info(f"[{self.job_id}] Starting DATA pipeline")
            self.monitor.start()

            # Step 1: Collection
            self.status = DataStatus.COLLECTING
            self._update_progress(0.0, "Initializing data collection...")

            raw_data = self.collector.collect(
                catalogue_items=catalogue_items,
                start_date=start_date,
                end_date=end_date,
                country_filters=countries,
                region_filters=regions,
                fail_on_any_error=fail_on_any_error,
            )

            self._update_progress(20.0, f"Collected {len(raw_data)} datasets from sources")

            # Step 2: Validation
            self.status = DataStatus.VALIDATING
            self._update_progress(25.0, "Validating data quality and completeness...")

            validation_report = self.validator.validate(raw_data)

            if validation_report.critical_errors > 0:
                logger.warning(f"[{self.job_id}] Validation found {validation_report.critical_errors} critical errors, continuing with valid data")
                # Filter out datasets that failed critical validation
                raw_data = {k: v for k, v in raw_data.items() if not v.empty}
                if not raw_data:
                    self.status = DataStatus.FAILED
                    self.monitor.fail("All datasets failed validation")
                    raise DataQualityError(
                        "Validation failed: no valid datasets available",
                        context={"job_id": self.job_id, "critical_errors": validation_report.critical_errors},
                    )

            self._update_progress(40.0, f"Validation complete: {len(validation_report.warnings)} warnings detected")

            # Step 3: Cleaning. Gaps are detected and reported, never filled:
            # forward-filling would inject values that had not been published at
            # those timestamps, and back-filling would read from the future.
            self.status = DataStatus.CLEANING
            self._update_progress(45.0, "Inspecting data for gaps...")

            clean_data, cleaning_report = self.cleaner.clean(
                raw_data,
                validation_report
            )

            self._update_progress(
                60.0,
                f"Gap inspection complete: {cleaning_report.gaps_detected} missing "
                f"cell(s) preserved for explicit handling",
            )

            # Step 4: Formatting
            self.status = DataStatus.FORMATTING
            self._update_progress(65.0, "Formatting data and engineering features...")

            formatted_data = self.formatter.format(
                clean_data,
                target_schema="engine_v1"
            )

            self._update_progress(80.0, f"Formatting complete: {len(formatted_data.columns)} features generated")

            # Step 5: Analysis
            self.status = DataStatus.ANALYZING
            self._update_progress(85.0, "Analyzing data quality and generating report...")

            analysis_report = self.analyzer.analyze(
                formatted_data,
                validation_report,
                cleaning_report
            )

            # Generate quality report (sub-scores only; the gate owns the score)
            quality_report = self._generate_quality_report(
                validation_report,
                cleaning_report,
                analysis_report
            )

            # Snapshot the exact rows the gate is about to verify.
            self.snapshot = self.snapshotter.capture(clean_data, job_id=self.job_id)

            # Nothing is certified — and therefore nothing reaches the model —
            # until the payload independently passes the quality gate. The gate
            # computes the composite from the raw sub-scores (there is no
            # parameter for a pre-computed score, so a flawed weighting upstream
            # cannot decide the verdict) and re-derives its own structural
            # checks, because the composite alone accepts an entirely empty
            # payload at exactly the 70/100 threshold.
            self.attestation = self.quality_gate.enforce(
                clean_data,
                job_id=self.job_id,
                components=quality_report.components,
                snapshot_id=self.snapshot.snapshot_id,
            )
            quality_report.quality_score = float(self.attestation.quality_score or 0.0)
            quality_report.fit_for_engine = self.attestation.verified
            quality_report.recommendation = self._recommendation_for(quality_report)

            self._update_progress(
                90.0,
                f"Analysis complete: gate-verified quality score "
                f"{quality_report.quality_score:.1f}/100",
            )

            # Step 6: Save and certify
            self.status = DataStatus.CERTIFIED
            self._update_progress(95.0, "Saving and certifying data package...")

            data_package = self._save_data_package(
                formatted_data,
                quality_report,
                start_date,
                end_date,
                user_id,
                regions=regions,
                countries=countries,
            )

            self._update_progress(100.0, f"Data certified and ready for training")
            self.monitor.complete(f"Data certified: {data_package.job_id}")

            logger.info(f"[{self.job_id}] DATA pipeline completed successfully")
            return data_package

        except Exception as e:
            self.status = DataStatus.FAILED
            self.monitor.fail(str(e))
            logger.error(f"[{self.job_id}] DATA pipeline failed: {e}")
            raise

    def _generate_quality_report(self,
                                validation_report,
                                cleaning_report,
                                analysis_report) -> DataQualityReport:
        """Decompose quality into sub-scores without computing the composite.

        The weighted average lives in the quality gate, which is the single owner
        of the verdict. Duplicating the weighting here is exactly how a flawed
        composite used to be able to decide whether data reached the model.
        """

        # Component sub-scores, measured from the validation/cleaning/analysis
        # stages. None are zero-filled: the gate excludes unmeasured components
        # from the composite instead of letting an absent measurement drag it down.
        components = QualityComponents(
            completeness=(1 - validation_report.missing_ratio) * 100,
            consistency=(1 - validation_report.inconsistency_ratio) * 100,
            timeliness=validation_report.timeliness_score * 100,
            accuracy=(
                None if analysis_report.accuracy_score is None
                else analysis_report.accuracy_score * 100
            ),
        )

        return DataQualityReport(
            job_id=self.job_id,
            quality_score=0.0,  # replaced by the gate's score in run()
            completeness=float(components.completeness if components.completeness is not None else 0.0),
            consistency=float(components.consistency if components.consistency is not None else 0.0),
            timeliness=float(components.timeliness if components.timeliness is not None else 0.0),
            accuracy=float(components.accuracy if components.accuracy is not None else 0.0),
            # Anomalies come from validation. Cleaning no longer contributes a
            # count of "fixed" cells, because it no longer fixes anything: gaps
            # are preserved, and filling them would inject values that were not
            # published at those timestamps.
            anomalies_detected=validation_report.anomalies_count,
            anomalies_fixed=0,
            warnings=validation_report.warnings + cleaning_report.warnings,
            errors=validation_report.errors,
            fit_for_engine=False,  # only the gate may certify a payload
            recommendation="",
            components=components,
            timestamp=datetime.now(timezone.utc)
        )

    @staticmethod
    def _recommendation_for(quality_report: DataQualityReport) -> str:
        """Operator wording derived from the gate's verdict, not a local score."""
        if not quality_report.fit_for_engine:
            return "❌ Data quality insufficient. Re-collection or additional cleaning recommended."
        if quality_report.quality_score >= 85.0:
            return "✅ Data quality excellent. Ready for ENGINE processing."
        return "⚠️ Data quality acceptable. Review warnings before proceeding."

    def _save_data_package(self,
                          data: pd.DataFrame,
                          quality_report: DataQualityReport,
                          start_date: str,
                          end_date: str,
                          user_id: str,
                          regions: Optional[List[str]] = None,
                          countries: Optional[List[str]] = None) -> DataPackage:
        """Save formatted data and create package."""

        # Create job-specific directory
        job_dir = f"{self.output_dir}"
        os.makedirs(job_dir, exist_ok=True)

        # Save datasets
        timeseries_path = f"{job_dir}/timeseries.parquet"
        features_path = f"{job_dir}/features.parquet"

        data.to_parquet(timeseries_path, compression='snappy')

        # Extract features
        features = self.formatter.extract_features(data)
        features.to_parquet(features_path, compression='snappy')

        return DataPackage(
            job_id=self.job_id,
            timeseries_path=timeseries_path,
            features_path=features_path,
            metadata={
                "start_date": start_date,
                "end_date": end_date,
                "num_sources": len(data['source'].unique()) if 'source' in data.columns else 0,
                "frequency": "daily",
                "regions": regions or [],
                "countries": countries or [],
                "quality_score": quality_report.quality_score,
                "quality_attestation": self.attestation.to_dict() if self.attestation else None,
                "dataset_snapshot": self.snapshot.to_dict() if self.snapshot else None,
                "snapshot_id": self.snapshot.snapshot_id if self.snapshot else None,
                "collection_report": (
                    self.collector.last_report.to_dict() if self.collector.last_report else None
                ),
            },
            quality_report=quality_report,
            date_range=(start_date, end_date),
            num_assets=len(data['asset'].unique()) if 'asset' in data.columns else 0,
            num_observations=len(data),
            certified_at=datetime.now(timezone.utc),
            certified_by=user_id,
            snapshot_id=self.snapshot.snapshot_id if self.snapshot else None,
        )
