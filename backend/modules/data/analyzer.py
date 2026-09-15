"""Data Analyzer - Statistical analysis and reporting."""

import logging
from typing import Dict, Optional

from dataclasses import dataclass, field
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

@dataclass
class AnalysisReport:
    accuracy_score: Optional[float] = None
    integrity_anomalies: int = 0
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

        # Round seven (R2): the previous "accuracy" was a hand-rolled
        # 0.4/0.3/0.3 blend whose validation term was a binary step, whose
        # cleaning term rewarded fixes the cleaner deliberately no longer
        # makes, and whose name described nothing measured. Accuracy at this
        # stage is not measurable; the gate renormalises its weights over the
        # components that ARE present, so absence is the honest value.
        report.accuracy_score = None

        # What IS measured here: structural anomalies the validator found,
        # carried per row-count so downstream reports can rate them.
        if validation_report is not None:
            report.integrity_anomalies = int(getattr(validation_report, "anomalies_count", 0) or 0)

        # Additional statistics
        value_col = 'value' if 'value' in data.columns else 'Value' if 'Value' in data.columns else None
        if value_col:
            values = pd.to_numeric(data[value_col], errors='coerce').dropna()
            if len(values) > 0:
                report.statistics.update({
                    "mean": float(values.mean()),
                    "std": float(values.std()),
                    "min": float(values.min()),
                    "max": float(values.max()),
                    "completeness": float(len(values) / len(data))
                })

        logger.info("[%s] Data quality accuracy: %s", self.job_id, "unmeasured" if report.accuracy_score is None else f"{report.accuracy_score:.2f}")

        return report
