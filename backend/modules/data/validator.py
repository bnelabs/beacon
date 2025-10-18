"""Data Validator - Quality checks and anomaly detection."""

import logging
from typing import Dict
from dataclasses import dataclass
import pandas as pd

logger = logging.getLogger(__name__)

@dataclass
class ValidationReport:
    critical_errors: int = 0
    warnings: list = None
    errors: list = None
    missing_ratio: float = 0.0
    inconsistency_ratio: float = 0.0
    timeliness_score: float = 1.0
    anomalies_count: int = 0

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []

class DataValidator:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def validate(self, data: Dict[str, pd.DataFrame]) -> ValidationReport:
        logger.info(f"[{self.job_id}] Validating {len(data)} datasets")
        report = ValidationReport()
        
        for code, df in data.items():
            if df.empty:
                report.errors.append({"code": code, "error": "Empty dataset"})
                report.critical_errors += 1
                continue
            
            # Missing values check
            total_cells = len(df) * len(df.columns)
            if total_cells > 0:
                missing_pct = df.isnull().sum().sum() / total_cells
                if missing_pct > 0.3:
                    report.warnings.append({"code": code, "warning": f"{missing_pct*100:.1f}% missing"})

        # Calculate overall missing ratio with safe division
        total_cells = sum(len(df) * len(df.columns) for df in data.values() if not df.empty)
        if total_cells > 0:
            report.missing_ratio = sum(df.isnull().sum().sum() for df in data.values() if not df.empty) / total_cells
        else:
            report.missing_ratio = 0.0

        return report
