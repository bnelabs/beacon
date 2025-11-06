"""DATA Module Orchestrator - Coordinates collection, validation, and preparation."""

import logging
import os
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

import pandas as pd
from sqlalchemy.orm import Session

from backend.models.data_catalogue import DataCatalogueItem
from backend.models.data_source import DataSource
from .collector import DataCollector
from .validator import DataValidator
from .cleaner import DataCleaner
from .formatter import DataFormatter
from .analyzer import DataAnalyzer
from .monitor import DataMonitor

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
    """Data quality assessment report."""
    job_id: str
    quality_score: float  # 0-100
    completeness: float  # % non-null
    consistency: float  # % passes validation
    timeliness: float  # % recent data
    accuracy: float  # % within expected ranges

    anomalies_detected: int
    anomalies_fixed: int
    warnings: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]

    fit_for_engine: bool
    recommendation: str

    timestamp: datetime


@dataclass
class DataPackage:
    """Prepared data package for ENGINE."""
    job_id: str
    timeseries_path: str
    features_path: str
    graph_path: Optional[str]

    metadata: Dict[str, Any]
    quality_report: DataQualityReport

    date_range: tuple
    num_assets: int
    num_observations: int

    certified_at: datetime
    certified_by: str


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

        self.status = DataStatus.PENDING
        self.current_step = None
        self.progress = 0.0

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
                    raise Exception("Validation failed: No valid datasets available")

            self._update_progress(40.0, f"Validation complete: {len(validation_report.warnings)} warnings detected")

            # Step 3: Cleaning
            self.status = DataStatus.CLEANING
            self._update_progress(45.0, "Cleaning data and imputing missing values...")

            clean_data, cleaning_report = self.cleaner.clean(
                raw_data,
                validation_report
            )

            self._update_progress(60.0, f"Data cleaning complete: Fixed {cleaning_report.fixed_issues} issues")

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

            # Generate quality report
            quality_report = self._generate_quality_report(
                validation_report,
                cleaning_report,
                analysis_report
            )

            self._update_progress(90.0, f"Analysis complete: Quality score {quality_report.quality_score:.1f}/100")

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
        """Generate comprehensive quality report."""

        # Calculate component scores
        completeness = (1 - validation_report.missing_ratio) * 100
        consistency = (1 - validation_report.inconsistency_ratio) * 100
        timeliness = validation_report.timeliness_score * 100
        accuracy = analysis_report.accuracy_score * 100

        # Overall quality score (weighted average)
        quality_score = (
            completeness * 0.25 +
            consistency * 0.25 +
            timeliness * 0.20 +
            accuracy * 0.30
        )

        # Determine if fit for engine
        fit_for_engine = (
            quality_score >= 70.0 and
            validation_report.critical_errors == 0 and
            completeness >= 80.0
        )

        # Generate recommendation
        if fit_for_engine:
            recommendation = "✅ Data quality excellent. Ready for ENGINE processing."
        elif quality_score >= 60.0:
            recommendation = "⚠️ Data quality acceptable but has issues. Review warnings before proceeding."
        else:
            recommendation = "❌ Data quality insufficient. Re-collection or additional cleaning recommended."

        return DataQualityReport(
            job_id=self.job_id,
            quality_score=quality_score,
            completeness=completeness,
            consistency=consistency,
            timeliness=timeliness,
            accuracy=accuracy,
            anomalies_detected=validation_report.anomalies_count + cleaning_report.anomalies_detected,
            anomalies_fixed=cleaning_report.fixed_issues,
            warnings=validation_report.warnings + cleaning_report.warnings,
            errors=validation_report.errors,
            fit_for_engine=fit_for_engine,
            recommendation=recommendation,
            timestamp=datetime.now(timezone.utc)
        )

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

        # Optional: Build graph structure
        graph_path = None
        if len(data) > 100:  # Only for sufficient data
            graph = self.formatter.build_graph(data)
            graph_path = f"{job_dir}/graph.pkl"
            import pickle
            with open(graph_path, 'wb') as f:
                pickle.dump(graph, f)

        return DataPackage(
            job_id=self.job_id,
            timeseries_path=timeseries_path,
            features_path=features_path,
            graph_path=graph_path,
            metadata={
                "start_date": start_date,
                "end_date": end_date,
                "num_sources": len(data['source'].unique()) if 'source' in data.columns else 0,
                "frequency": "daily",
                "regions": regions or [],
                "countries": countries or [],
                "quality_score": quality_report.quality_score,
            },
            quality_report=quality_report,
            date_range=(start_date, end_date),
            num_assets=len(data['asset'].unique()) if 'asset' in data.columns else 0,
            num_observations=len(data),
            certified_at=datetime.now(timezone.utc),
            certified_by=user_id
        )
