"""Data Analyzer - Statistical analysis and reporting."""

import logging
from typing import Dict
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

@dataclass
class AnalysisReport:
    accuracy_score: float = 0.0
    statistics: Dict = field(default_factory=dict)

class DataAnalyzer:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def analyze(self, data: pd.DataFrame, validation_report, cleaning_report) -> AnalysisReport:
        logger.info(f"[{self.job_id}] Analyzing data")

        report = AnalysisReport()

        if data.empty:
            return report

        # Basic statistics
        report.statistics = {
            "rows": len(data),
            "columns": len(data.columns),
            "memory_mb": float(data.memory_usage(deep=True).sum() / 1024**2)
        }

        # Compute data quality score based on validation and cleaning
        quality_factors = []

        # Factor 1: Validation results (40% weight)
        if validation_report and hasattr(validation_report, 'critical_errors'):
            validation_score = 1.0 if validation_report.critical_errors == 0 else 0.0
            quality_factors.append(validation_score * 0.4)

        # Factor 2: Data completeness (30% weight)
        if 'value' in data.columns:
            completeness = 1.0 - (data['value'].isnull().sum() / len(data))
            quality_factors.append(completeness * 0.3)

        # Factor 3: Cleaning success (30% weight)
        if cleaning_report and hasattr(cleaning_report, 'fixed_issues'):
            # Reward successful cleaning, penalize if many issues
            cleaning_score = 1.0 / (1.0 + cleaning_report.fixed_issues / len(data))
            quality_factors.append(cleaning_score * 0.3)

        # Overall accuracy score
        report.accuracy_score = float(sum(quality_factors)) if quality_factors else 0.5

        # Additional statistics
        if 'value' in data.columns:
            values = data['value'].dropna()
            if len(values) > 0:
                report.statistics.update({
                    "mean": float(values.mean()),
                    "std": float(values.std()),
                    "min": float(values.min()),
                    "max": float(values.max()),
                    "completeness": float(len(values) / len(data))
                })

        logger.info(f"[{self.job_id}] Data quality score: {report.accuracy_score:.2f}")

        return report
