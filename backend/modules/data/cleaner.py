"""Data cleaning: gap detection and anomaly flagging, without imputation.

This module previously forward- and back-filled every column
(``df.ffill().bfill()``) and counted the filled cells as "fixed issues".

Both directions are look-ahead:

* ``ffill`` copies the last observed value forward. When a series is published
  late or revised, forward-filling writes the pre-gap level into the post-gap
  period, so anything downstream reads a value that did not exist at that
  timestamp. The frame looks complete while being partly synthetic.
* ``bfill`` is strictly worse: it copies a *future* value backwards, so every
  cell it fills carries information from after that date. That is direct
  leakage from the future into the past.

A cleaning step cannot repair a missing observation -- the observation is simply
absent from the record. What it can do is make the gaps explicit and measurable
so that (a) the model receives a mask alongside the values and can distinguish
"reported as zero" from "not reported", and (b) the quality gate scores
completeness from reality rather than from a frame that imputation has made
appear complete.

So this module detects and reports; it does not fill.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CleaningReport:
    """What was found in the raw frames. Nothing here was filled in."""

    gaps_detected: int = 0
    gaps_by_source: Dict[str, int] = field(default_factory=dict)
    empty_sources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "gaps_detected": self.gaps_detected,
            "gaps_by_source": dict(self.gaps_by_source),
            "empty_sources": list(self.empty_sources),
            "warnings": list(self.warnings),
            "imputation": "none",
        }


class DataCleaner:
    """Detects gaps without imputing them."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def clean(
        self,
        data: Dict[str, pd.DataFrame],
        validation_report=None,
    ) -> Tuple[Dict[str, pd.DataFrame], CleaningReport]:
        """Return the frames unchanged, plus a report of their gaps.

        The returned frames are the inputs. Callers that need a filled value for
        a model input must supply an explicit mask; nothing here fabricates one,
        because a fabricated value cannot be distinguished from a real one after
        the fact.
        """
        logger.info("[%s] Inspecting %d dataset(s) for gaps", self.job_id, len(data))
        report = CleaningReport()
        cleaned: Dict[str, pd.DataFrame] = {}

        for code, frame in data.items():
            if frame is None or frame.empty:
                report.empty_sources.append(code)
                cleaned[code] = frame
                continue

            missing = int(frame.isnull().sum().sum())
            if missing:
                report.gaps_detected += missing
                report.gaps_by_source[code] = missing
                logger.info(
                    "[%s] %s has %d missing cell(s); preserved, not imputed",
                    self.job_id, code, missing,
                )

            cleaned[code] = frame

        if report.gaps_detected:
            report.warnings.append(
                f"{report.gaps_detected} missing cell(s) preserved as NaN across "
                f"{len(report.gaps_by_source)} source(s). Downstream consumers must "
                "handle them explicitly: filling them would inject values that were "
                "not published at those timestamps."
            )

        if report.empty_sources:
            report.warnings.append(
                f"{len(report.empty_sources)} source(s) returned no rows: "
                f"{', '.join(sorted(report.empty_sources))}"
            )

        return cleaned, report
