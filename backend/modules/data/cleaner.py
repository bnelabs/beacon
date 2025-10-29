"""Data Cleaner - Missing value imputation and outlier handling."""

import logging
from typing import Dict, Tuple, List
from dataclasses import dataclass, field
import pandas as pd

logger = logging.getLogger(__name__)

@dataclass
class CleaningReport:
    fixed_issues: int = 0
    anomalies_detected: int = 0
    warnings: List[str] = field(default_factory=list)

class DataCleaner:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def clean(self, data: Dict[str, pd.DataFrame], validation_report) -> Tuple[Dict[str, pd.DataFrame], CleaningReport]:
        logger.info(f"[{self.job_id}] Cleaning {len(data)} datasets")
        cleaned = {}
        report = CleaningReport()
        
        for code, df in data.items():
            if df.empty:
                cleaned[code] = df
                continue
            
            # Forward fill missing values
            df_clean = df.ffill().bfill()
            cleaned[code] = df_clean
            
            fixed = df.isnull().sum().sum() - df_clean.isnull().sum().sum()
            report.fixed_issues += fixed
        
        return cleaned, report
