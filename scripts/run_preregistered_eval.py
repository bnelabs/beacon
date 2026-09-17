#!/usr/bin/env python
"""Pre-registered early-warning evaluation runner (protocols v1 and v2).

This script EXECUTES the protocols frozen in ``docs/prereg/early_warning_v1.md``
/ ``configs/event_eval_v1.yaml`` and ``docs/prereg/early_warning_v2.md`` /
``configs/event_eval_v2.yaml``. It is the glue step of
``docs/probes/event_target_proposal.md``; the proposal is the rationale, the
protocol files are the contracts, and this file is the machine that honours
them.

Discipline encoded here (and enforced by each protocol's single-run rule):

* every number in this file -- windows, quantiles, thresholds, model config,
  permutation seed -- is a protocol constant duplicated from the YAMLs. If a
  value here disagrees with the tagged YAML, that is a bug; the YAML and the
  tag win. v2 changes ONLY the family and adds the licence screen; every
  evaluation criterion, model setting and window is shared with v1 by
  construction (one module-level set of constants), because v2 exists to fix
  the diagnosed flaw -- an under-powered family -- and nothing else. Moving a
  criterion between runs would be moving goalposts.
* skips are data-availability or licence decisions applied BEFORE any metric
  is computed (fetch failure, licence prohibition, declared coverage floor,
  frequency rule, quality gate). Nothing is skipped because of a result.
* labels never touch features: ``label_events`` sees the raw series; the
  model sees windows that end before the labelled step; the split between
  training data (<= 2006) and the evaluation window (2007+) is chronological.
* scores are sign-adjusted by the registry's stress direction so "higher =
  more stress" for every indicator, and labels are joined to scores through
  ``row_offset`` (the RiskSeriesResult contract), never by truncation.
* credentials: v2 fetches through the FRED API with ``FRED_API_KEY`` read
  from the environment. The key is NEVER written to any file: recorded
  endpoints carry ``api_key=<redacted>``, and the fetched CSVs plus their
  hashes are the committed provenance.
* the run is sequential per indicator with small models and explicit
  teardown, so it fits a 2-CPU / <1GB host: pre-registration is about the
  rules, not about compute.

Phases (per protocol):
    --fetch   download the declared family through the platform's own FRED
              plugin, licence-screen every candidate (v2), validate, hash,
              apply the coverage/frequency rules, write the manifest
    --eval    certify (quality gate), train, label, score, apply the frozen
              criteria, write the report under docs/prereg/runs/

Deviation, stated because the protocols state it: runs execute in-process
rather than through the Celery job queue. The computation mirrors
``run_backtest``'s event idiom (same labeller, same metric functions, same
alarm rule) with the alignment and direction corrections that idiom received
alongside protocol v1.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prereg-eval")

# --------------------------------------------------------------------------
# Protocol constants -- SHARED by v1 and v2 (frozen; the tags win)
# --------------------------------------------------------------------------
EVAL_START = pd.Timestamp("2007-01-01")
EVAL_END = pd.Timestamp("2024-12-31")
TRAIN_END = pd.Timestamp("2006-12-31")
QUANTILE = 0.95           # labeller: quantile of the horizon-move distribution
HORIZON = 21              # labeller: business-day steps the move accumulates over
MIN_DURATION = 5          # labeller: consecutive crossing steps to constitute an event
MAX_LEAD = 2 * HORIZON    # lead-time horizon, same convention as run_backtest
ALARM_QUANTILE = 0.95     # alarm rule: top (1-q) of the score series, run_backtest idiom
MIN_COVERAGE_FRAC = 0.60  # declared data-availability floor for the eval window
MIN_EPISODES = 3          # declared minimum of fully-covered stress episodes
MIN_TESTABLE_FAMILY = 3   # system-level claim needs at least this many TESTED indicators
PERM_ITERATIONS = 1000    # permutation test for average precision
PERM_SEED = 20260917      # frozen seed
HOLM_ALPHA = 0.05         # family-wise level for the Holm-Bonferroni adjustment
BUSINESS_DAYS_PER_YEAR = 252

# Criteria (frozen; identical for every protocol version by design)
MIN_MEDIAN_LEAD = 10          # business days
MAX_FALSE_ALARMS_PER_QUIET_YEAR = 4.0

# Declared episode family (proposal section 2.1). Context/sanity only: the
# labels the metrics run against are the labeller's endogenous events.
EPISODES: Dict[str, Tuple[str, str]] = {
    "E1_gfc":            ("2007-08-01", "2009-03-31"),
    "E2_euro_area":      ("2010-05-01", "2012-07-31"),
    "E3_em_outflows":    ("2015-08-01", "2016-02-29"),
    "E4_repo_spike":     ("2019-09-15", "2019-10-15"),
    "E5_dash_for_cash":  ("2020-02-20", "2020-04-15"),
    "E6_uk_ldi":         ("2022-09-23", "2022-10-31"),
    "E7_regional_banks": ("2023-03-08", "2023-05-31"),
}

# --------------------------------------------------------------------------
# Families, per protocol version. Dispositions are decisions and recorded
# facts, declared before the protocol's fetch -- never results.
# --------------------------------------------------------------------------
_OPERATOR_REPORTED = "operator-reported series; no public source in the evaluation environment"

FAMILY_V1: Dict[str, Dict[str, Any]] = {
    "FRED_STLFSI4":      {"source": "fred", "series_id": "STLFSI4"},
    "FRED_KCFSI":        {"source": "fred", "series_id": "KCFSI"},
    "FRED_SOFR":         {"source": "fred", "series_id": "SOFR"},
    "FRED_BAMLH0A0HYM2": {"source": "fred", "series_id": "BAMLH0A0HYM2"},
    "FRED_T10Y2Y":       {"source": "fred", "series_id": "T10Y2Y"},
    # One declared keyless attempt at FRED id "CISS"; a 404 is recorded as a
    # fetch skip, and no substitute source is improvised.
    "ECB_CISS":          {"source": "fred", "series_id": "CISS"},
    "FRED_RRPONTSYD":    {"excluded": "owner decision: the registry itself flags its direction as a funding-sense judgement (proposal section 6)"},
    "HQLA_LEVEL":        {"excluded": _OPERATOR_REPORTED},
    "LCR_RATIO":         {"excluded": _OPERATOR_REPORTED},
    "NSFR_RATIO":        {"excluded": _OPERATOR_REPORTED},
    "BANK_EQUITY_INDEX": {"excluded": _OPERATOR_REPORTED},
    "FX_SWAP_BASIS":     {"excluded": _OPERATOR_REPORTED},
    "CDS_PREMIUM":       {"excluded": _OPERATOR_REPORTED},
}

# v2 = v1's candidate set (rules re-derive every skip at fetch time; nothing
# is excluded merely because v1 skipped it) PLUS the two literature-backed
# daily series curated for v2: T10Y3M (the short-end curve spread the
# recession literature documents) and VIXCLS (the standard equity-stress
# gauge; FRED serves it "reprinted with permission", full history from 1990,
# no reproduction prohibition -- series notes checked 2026-09-17). The
# selection rationale predates any v2 fetch; see the protocol document.
FAMILY_V2: Dict[str, Dict[str, Any]] = {
    **{k: v for k, v in FAMILY_V1.items()},
    "FRED_T10Y3M":       {"source": "fred", "series_id": "T10Y3M"},
    "FRED_VIXCLS":       {"source": "fred", "series_id": "VIXCLS"},
}

# Terms-of-use phrases that PROHIBIT the reproduction/redistribution this
# repository performs by committing fetched series as provenance. A match is
# a licence skip, applied before any data is downloaded.
LICENCE_PROHIBITION_RE = re.compile(
    r"reproduction of this data in any form is prohibited"
    r"|not authorized or permitted to publish"
    r"|provided for your internal use only"
    r"|without (?:the )?prior written (?:permission|approval)",
    re.IGNORECASE,
)

PROTOCOLS: Dict[str, Dict[str, Any]] = {
    "v1": {
        "name": "early_warning_v1",
        "tag": "prereg-early-warning-v1",
        "family": FAMILY_V1,
        "data_dir": REPO / "data" / "prereg",
        "report_dir": REPO / "docs" / "prereg" / "runs" / "early_warning_v1",
        "keyed": False,
        "licence_screen": False,
        # Frozen at tag time; never re-derived.
        "alarm_quantile": 0.95,
        "scorers": ("tan_frozen",),
    },
    "v2": {
        "name": "early_warning_v2",
        "tag": "prereg-early-warning-v2",
        "family": FAMILY_V2,
        "data_dir": REPO / "data" / "prereg" / "v2",
        "report_dir": REPO / "docs" / "prereg" / "runs" / "early_warning_v2",
        "keyed": True,
        "licence_screen": True,
        "alarm_quantile": 0.95,
        "scorers": ("tan_frozen",),
    },
    "v3": {
        "name": "early_warning_v3",
        "tag": "prereg-early-warning-v3",
        # Family = v2's, unchanged: the rules re-derive every skip at fetch
        # time on a fresh, self-contained manifest. v3 changes the alarm
        # operating point (declared from published v1/v2 arithmetic) and adds
        # the literature-standard hazard scorer -- nothing else.
        "family": FAMILY_V2,
        "data_dir": REPO / "data" / "prereg" / "v3",
        "report_dir": REPO / "docs" / "prereg" / "runs" / "early_warning_v3",
        "keyed": True,
        "licence_screen": True,
        # Declared arithmetic (published v1/v2 facts only): at q95 alarms fire
        # on ~5% of days (~12.6/yr) with measured precision ~23-29%, giving
        # ~9-10 false alarms per quiet year against a ceiling of 4 -- the
        # criterion was unreachable at that operating point for ANY indicator.
        # FA/yr = alarms/yr * (1 - precision); at q98 (~2% of days, ~5/yr) the
        # ceiling of 4 requires precision >= ~20%, about what was measured at
        # q95 and plausibly better at a rarer point. Demanding, not soft.
        "alarm_quantile": 0.98,
        "scorers": ("tan_frozen", "hazard_logit"),
    },
}

MODEL_CONFIG: Dict[str, Any] = {
    "model": "temporal_attention",
    "epochs": 15,
    "sequence_length": 30,
    "batch_size": 64,
    "d_model": 16,
    "nhead": 2,
    "num_layers": 1,
    "dropout": 0.0,
    "learning_rate": 0.001,
    "mixed_precision": False,
}

RUN_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Phase 1: fetch
# --------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fred_api_key(proto: Dict[str, Any]) -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if proto["keyed"] and not key:
        raise SystemExit(
            "protocol v2 fetches through the keyed FRED API (licence screening "
            "and full histories need it); set FRED_API_KEY in the environment. "
            "The key is never written to any file."
        )
    return key


def _licence_screen(series_id: str, api_key: str) -> Tuple[bool, str, List[str]]:
    """Return (prohibited, reason, licence_lines) from the series' own notes."""
    import requests

    response = requests.get(
        "https://api.stlouisfed.org/fred/series",
        params={"series_id": series_id, "api_key": api_key, "file_type": "json"},
        timeout=25,
    )
    if response.status_code != 200:
        return False, f"metadata HTTP {response.status_code}", []
    payload = response.json()
    series = (payload.get("seriess") or [{}])[0]
    notes = series.get("notes") or ""
    lines = [
        line.strip()
        for line in notes.split("\n")
        if re.search(r"copyright|licen[cs]e|permission|reproduc|redistribut|internal use", line, re.I)
    ]
    match = LICENCE_PROHIBITION_RE.search(notes)
    if match:
        return True, match.group(0), lines
    return False, "", lines


def fetch_phase(proto: Dict[str, Any]) -> int:
    from backend.plugins.fred_plugin import FREDPlugin

    data_dir: Path = proto["data_dir"]
    data_dir.mkdir(parents=True, exist_ok=True)
    api_key = _fred_api_key(proto)
    plugin = FREDPlugin(config={"api_key": api_key} if api_key else {})
    transport = (
        "fred_plugin (keyed FRED API; api_key redacted)"
        if api_key else "fred_plugin (keyless fredgraph.csv)"
    )
    manifest: Dict[str, Any] = {
        "protocol": proto["name"],
        "tag": proto["tag"],
        "fetched_at": RUN_STARTED_AT,
        "transport": transport,
        "eval_window": [str(EVAL_START.date()), str(EVAL_END.date())],
        "entries": {},
    }
    eval_busdays = int(np.busday_count(EVAL_START.date(), (EVAL_END + pd.Timedelta(days=1)).date()))

    for code, spec in proto["family"].items():
        if "excluded" in spec:
            manifest["entries"][code] = {"status": "excluded", "reason": spec["excluded"]}
            continue

        series_id = spec["series_id"]
        entry: Dict[str, Any] = {
            "status": "pending",
            "source": transport,
            "series_id": series_id,
            "endpoint": (
                f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key=<redacted>"
                if api_key else
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            ),
        }

        # Licence screen BEFORE any data download: committing a series whose
        # terms prohibit reproduction would make the provenance store itself
        # the violation. (This is why v1's BAMLH0A0HYM2 csv was removed.)
        if proto["licence_screen"]:
            prohibited, reason, licence_lines = _licence_screen(series_id, api_key)
            entry["licence_lines"] = licence_lines[:4]
            if prohibited:
                entry.update(
                    status="skipped", skip_reason="licence_prohibits_reproduction",
                    detail=f"series notes contain: {reason!r} -- committing it as provenance would violate the terms",
                )
                manifest["entries"][code] = entry
                logger.warning("%s: licence skip (%s)", code, reason)
                continue
            if reason.startswith("metadata HTTP"):
                entry.update(status="skipped", skip_reason="fetch_failed",
                             detail=f"licence screen could not read series metadata: {reason}")
                manifest["entries"][code] = entry
                continue

        try:
            frame = plugin.fetch_indicator_data(
                series_id,
                datetime(1970, 1, 1),
                datetime(EVAL_END.year, EVAL_END.month, EVAL_END.day),
            )
        except Exception as exc:  # typed plugin errors and network facts alike
            entry.update(status="skipped", skip_reason="fetch_failed",
                         detail=f"{type(exc).__name__}: {exc}"[:300])
            manifest["entries"][code] = entry
            logger.warning("%s: fetch failed (%s)", code, entry["detail"])
            continue

        if frame is None or frame.empty:
            entry.update(status="skipped", skip_reason="fetch_failed", detail="empty payload")
            manifest["entries"][code] = entry
            continue

        frame = frame.copy()
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        frame["Value"] = pd.to_numeric(frame["Value"], errors="coerce")
        frame = frame.dropna(subset=["Date"]).drop_duplicates(subset=["Date"]).sort_values("Date")

        csv_path = data_dir / f"{code}.csv"
        frame.to_csv(csv_path, index=False)

        eval_rows = frame[(frame["Date"] >= EVAL_START) & (frame["Date"] <= EVAL_END)]
        coverage_frac = float(len(eval_rows)) / eval_busdays if eval_busdays else 0.0

        # Frequency is a data-availability fact, measured before any metric:
        # the protocol's step is one business day, so weekly/monthly series
        # are skipped rather than silently resampled (resampling rules are
        # declared v3 work, not mid-run improvisation).
        gaps = frame["Date"].diff().dt.days.dropna()
        median_gap = float(gaps.median()) if len(gaps) else float("nan")
        frequency = "daily" if median_gap <= 1.5 else ("weekly" if median_gap <= 8 else ("monthly" if median_gap <= 35 else "other"))

        span_lo, span_hi = (eval_rows["Date"].min(), eval_rows["Date"].max()) if len(eval_rows) else (None, None)
        episodes_covered = []
        if span_lo is not None:
            for name, (lo, hi) in EPISODES.items():
                if pd.Timestamp(lo) >= span_lo and pd.Timestamp(hi) <= span_hi:
                    episodes_covered.append(name)

        entry.update(
            csv=str(csv_path.relative_to(REPO)),
            sha256=_sha256(csv_path),
            rows_total=int(len(frame)),
            rows_eval=int(len(eval_rows)),
            series_start=str(frame["Date"].min().date()),
            series_end=str(frame["Date"].max().date()),
            median_gap_days=median_gap,
            frequency=frequency,
            coverage_frac=round(coverage_frac, 4),
            episodes_covered=episodes_covered,
            nan_ratio_eval=round(float(eval_rows["Value"].isna().mean()), 4) if len(eval_rows) else None,
        )
        if frequency != "daily":
            entry.update(status="skipped", skip_reason="frequency_not_daily",
                         detail=f"median observation gap {median_gap:.0f} days ({frequency}); the protocol step is one business day")
        elif coverage_frac < MIN_COVERAGE_FRAC or len(episodes_covered) < MIN_EPISODES:
            entry.update(status="skipped", skip_reason="insufficient_coverage",
                         detail=(f"coverage {coverage_frac:.2f} < {MIN_COVERAGE_FRAC} or "
                                 f"{len(episodes_covered)} covered episodes < {MIN_EPISODES}"))
        else:
            entry["status"] = "testable"
        manifest["entries"][code] = entry
        logger.info("%s: %s (coverage %.2f, episodes %d)", code, entry["status"], coverage_frac, len(episodes_covered))

    testable = [c for c, e in manifest["entries"].items() if e.get("status") == "testable"]
    manifest["testable_family"] = testable
    manifest_path = data_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("manifest written: %d testable, %d skipped, %d excluded",
                len(testable),
                sum(1 for e in manifest["entries"].values() if e.get("status") == "skipped"),
                sum(1 for e in manifest["entries"].values() if e.get("status") == "excluded"))
    return 0


# --------------------------------------------------------------------------
# Phase 2 helpers (identical computation for every protocol version)
# --------------------------------------------------------------------------

def _wilson_ci(successes: int, trials: int, z: float = 1.96) -> Tuple[float, float]:
    if trials == 0:
        return (float("nan"), float("nan"))
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _holm(pvals: Dict[str, float], alpha: float) -> Dict[str, bool]:
    """Holm-Bonferroni: returns per-hypothesis 'survives at alpha'."""
    ordered = sorted(pvals.items(), key=lambda kv: kv[1])
    n = len(ordered)
    survives: Dict[str, bool] = {}
    rejected_any = False
    for rank, (name, p) in enumerate(ordered):
        adjusted = (n - rank) * p
        if not rejected_any and adjusted > alpha:
            rejected_any = True
        survives[name] = not rejected_any
    return survives


def _permutation_ap_pvalue(labels: np.ndarray, scores: np.ndarray, observed_ap: float) -> float:
    from backend.modules.engine.event_metrics import average_precision

    rng = np.random.default_rng(PERM_SEED)
    count = 0
    labels_pool = labels.copy()
    for _ in range(PERM_ITERATIONS):
        rng.shuffle(labels_pool)
        try:
            perm_ap = average_precision(labels_pool, scores)
        except ValueError:
            continue  # a shuffle with no positive labels has no AP; not a count
        if perm_ap >= observed_ap:
            count += 1
    return (1 + count) / (1 + PERM_ITERATIONS)


# Hazard-scorer constants (protocol v3; declared, never tuned)
HAZARD_LOOKBACK = 63  # business-day gap feature, ~ one quarter


def _hazard_logit_scores(
    train_values: np.ndarray,
    train_mean: float,
    train_std: float,
    direction_sign: float,
    definition: Any,
    eval_values: np.ndarray,
    offsets: np.ndarray,
) -> Optional[np.ndarray]:
    """The frozen hazard-logit scorer (protocol v3's second declared scorer).

    The crisis-prediction literature's standard EWS architecture: instead of
    forecasting the indicator's next *level* (the TAN scorer's task, and a
    weak proxy for warning), estimate P(a stress episode ONSETS within
    `horizon` steps | the indicator's current state).

    Everything is declared, nothing tuned:

    * features (2): the direction-signed standardized level ``z_t`` and its
      ``HAZARD_LOOKBACK``-step change ``z_t - z_{t-lookback}`` (clamped at
      the series start; past information only). Non-finite ``z`` is imputed
      at 0 -- the standardized training mean -- matching the engine's
      documented gap convention in ``_prepare_sequence``;
    * fit labels: episode onsets within the next ``horizon`` steps, computed
      by the same labeller on the TRAIN span with the train span as its
      threshold span -- labels look forward *within training* and never
      cross into the evaluation span;
    * estimator: ``sklearn.linear_model.LogisticRegression`` at library
      defaults (L2, C=1.0, lbfgs, no class weighting), fitted once on the
      training span -- the same frozen-small-model discipline as the TAN.
      No knob is exposed, so none can be turned after seeing results;
    * score: ``decision_function`` over the evaluation grid. The criteria
      are rank-based (AUC, AP, quantile alarms), so the monotone logit
      scale is the honest score; nothing claims these are calibrated
      probabilities.

    Returns ``None`` when the training span contains no onsets at all --
    nothing to learn from is declared absence, not zero signal.
    """
    from sklearn.linear_model import LogisticRegression

    from backend.modules.data.event_labeller import label_events

    def _features(values: np.ndarray, idx: np.ndarray) -> np.ndarray:
        z = direction_sign * (values - train_mean) / train_std
        z = np.where(np.isfinite(z), z, 0.0)
        look = np.maximum(idx - HAZARD_LOOKBACK, 0)
        return np.column_stack([z[idx], z[idx] - z[look]])

    train_labelling = label_events(
        train_values, definition, threshold_span=(0, train_values.size)
    )
    if train_labelling.onsets.size == 0:
        return None

    horizon = int(definition.horizon)
    y = np.zeros(train_values.size, dtype=int)
    for onset in train_labelling.onsets:
        o = int(onset)
        y[max(0, o - horizon):o] = 1  # onset in (t, t+horizon]  <=>  t in [o-horizon, o-1]

    logit = LogisticRegression(max_iter=1000)
    logit.fit(_features(train_values, np.arange(train_values.size)), y)
    return logit.decision_function(_features(eval_values, np.asarray(offsets, dtype=int)))


def _evaluate_indicator(code: str, entry: Dict[str, Any], proto: Dict[str, Any]) -> Dict[str, Any]:
    import torch

    from backend.modules.data.event_labeller import EventDefinition, label_events
    from backend.modules.data.quality_gate import DataQualityGate
    from backend.modules.data.semantics import event_direction, stress_direction
    from backend.modules.engine.event_metrics import (
        average_precision,
        false_alarm_stats,
        lead_time_stats,
        roc_auc,
    )
    from backend.modules.engine.multi_scale_trainer import MultiScaleTrainer
    from backend.modules.engine.prediction_engine import RealPredictionEngine

    data_dir: Path = proto["data_dir"]
    out: Dict[str, Any] = {"code": code, "direction": event_direction(code)}
    direction_sign = 1.0 if stress_direction(code) >= 0 else -1.0

    frame = pd.read_csv(REPO / entry["csv"], parse_dates=["Date"])
    frame = frame.sort_values("Date").reset_index(drop=True)
    train_frame = frame[frame["Date"] <= TRAIN_END][["Date", "Value"]].reset_index(drop=True)
    eval_frame = frame[(frame["Date"] >= EVAL_START) & (frame["Date"] <= EVAL_END)][["Date", "Value"]].reset_index(drop=True)
    out["rows_train"], out["rows_eval"] = int(len(train_frame)), int(len(eval_frame))

    # 1. Certification: the real quality gate, on the evaluation payload.
    gate = DataQualityGate()
    attestation = gate.evaluate({code: eval_frame}, job_id=f"prereg-{proto['name']}-{code}")
    out["quality_gate"] = {
        "verified": bool(attestation.verified),
        "quality_score": attestation.quality_score,
        "score_source": attestation.score_source,
        "failures": [c.name for c in attestation.failures],
    }
    if not attestation.verified:
        out["status"] = "skipped"
        out["skip_reason"] = "quality_gate_failed"
        return out

    # 2. Train the frozen small model on the pre-2007 span only. Production
    # pairing: MultiScaleTrainer checkpoints carry the architecture config,
    # source_stats and sources that RealPredictionEngine._load_model reads.
    workdir = data_dir / "work" / code
    workdir.mkdir(parents=True, exist_ok=True)
    train_frame = train_frame.assign(source_code=code)
    eval_frame = eval_frame.assign(source_code=code)
    split_at = int(len(train_frame) * 0.8)
    trainer = MultiScaleTrainer(model_type="temporal_attention", device=torch.device("cpu"),
                                config=dict(MODEL_CONFIG))
    torch.manual_seed(11)  # frozen training seed; member of the protocol, not a tuned value
    trainer.train(
        train_df=train_frame.iloc[:split_at],
        val_df=train_frame.iloc[split_at:],
        test_df=eval_frame,
        output_dir=str(workdir),
    )
    checkpoint_path = workdir / "best_model.pt"
    if not checkpoint_path.exists():
        out["status"] = "failed"
        out["error"] = "training produced no checkpoint"
        return out

    # Training-span statistics for the baselines (the engine reads its own
    # source_stats from the checkpoint, which MultiScaleTrainer saved).
    train_values = pd.to_numeric(train_frame["Value"], errors="coerce").to_numpy(dtype=float)
    finite = train_values[np.isfinite(train_values)]

    # 3. Out-of-sample per-timestep risk series over the evaluation window.
    engine = RealPredictionEngine(str(checkpoint_path), torch.device("cpu"),
                                  {"sequence_length": MODEL_CONFIG["sequence_length"],
                                   "job_id": f"prereg-{proto['name']}-{code}"})
    payload = eval_frame.rename(columns={"Value": "Close"}).assign(source_code=code)
    risk_series = engine.predict_risk_series(payload, attestation=attestation, batch_size=256)
    block = risk_series.frame[risk_series.frame["source"] == code]
    offsets = np.asarray(block["row_offset"], dtype=int)
    scores_raw = np.asarray(block["risk_score"], dtype=float)

    values_eval = pd.to_numeric(eval_frame["Value"], errors="coerce").to_numpy(dtype=float)
    keep = (offsets >= 0) & (offsets < values_eval.size) & np.isfinite(scores_raw)
    offsets, scores = offsets[keep], scores_raw[keep] * direction_sign
    if offsets.size < HORIZON + MIN_DURATION + 1:
        out["status"] = "skipped"
        out["skip_reason"] = "risk_series_too_short"
        return out

    # 4. Labels on the raw series (never on features), joined via row_offset.
    definition = EventDefinition(direction=event_direction(code), quantile=QUANTILE,
                                 horizon=HORIZON, min_duration=MIN_DURATION)
    labelling = label_events(values_eval, definition, threshold_span=(0, values_eval.size))
    events = labelling.events[offsets]
    if not events.any():
        out["status"] = "skipped"
        out["skip_reason"] = "no_events_in_window"
        out["labelling"] = {"n_events": int(labelling.n_events), "threshold": float(labelling.threshold)}
        return out

    # 5. Baselines on the identical aligned grid.
    mean = float(finite.mean()); std = float(finite.std()) or 1.0
    z_eval = (values_eval[offsets] - mean) / std
    z_train = (train_values[np.isfinite(train_values)] - mean) / std
    persistence_scores = direction_sign * z_eval
    slope, intercept = np.polyfit(z_train[:-1], z_train[1:], 1)
    ar1_scores = direction_sign * (intercept + slope * z_eval)

    # The alarm quantile is a PROTOCOL constant: each tagged version declares
    # its own (v1/v2: 0.95; v3: 0.98, derived from published v1/v2 operating-
    # point arithmetic). Applying a newer version's rule to an older run would
    # rewrite history; the lookup gives every run its own tag's rule.
    alarm_q = float(proto.get("alarm_quantile", ALARM_QUANTILE))

    def _score_card(sc: np.ndarray) -> Dict[str, Any]:
        alarms = sc >= float(np.quantile(sc, alarm_q))
        lead = lead_time_stats(events, alarms, max_lead=MAX_LEAD)
        fa = false_alarm_stats(alarms, events, horizon=HORIZON)
        return {
            "roc_auc": roc_auc(events, sc),
            "average_precision": average_precision(events, sc),
            "lead_time": lead,
            "false_alarms": fa,
            "n_alarms": int(alarms.sum()),
        }

    pers_card = _score_card(persistence_scores)
    ar1_card = _score_card(ar1_scores)
    base_rate = float(events.mean())
    quiet_years = float((events.size - events.sum())) / BUSINESS_DAYS_PER_YEAR

    # Declared scorers, each graded identically on the identical grid with
    # the identical frozen criteria. v1/v2 declare one (the frozen TAN); v3
    # adds the hazard logit -- both declared in the tagged protocol pre-run.
    scorer_series: Dict[str, Optional[np.ndarray]] = {"tan_frozen": scores}
    if "hazard_logit" in proto.get("scorers", ()):
        scorer_series["hazard_logit"] = _hazard_logit_scores(
            train_values, mean, std, direction_sign, definition, values_eval, offsets
        )

    scorers_out: Dict[str, Any] = {}
    for scorer_name in proto.get("scorers", ("tan_frozen",)):
        sc = scorer_series.get(scorer_name)
        if sc is None:
            scorers_out[scorer_name] = {"skipped": "no_onsets_in_training_span"}
            continue
        card = _score_card(sc)
        ap_obs = card["average_precision"]
        p_value = (
            _permutation_ap_pvalue(events.astype(bool), sc, ap_obs)
            if np.isfinite(ap_obs) else 1.0
        )
        n_true = int(card["false_alarms"].get("n_true_alarms", 0))
        n_false = int(card["false_alarms"].get("n_false_alarms", 0))
        precision_ci = _wilson_ci(n_true, n_true + n_false)
        median_lead = card["lead_time"].get("median_lead")
        fa_per_quiet_year = (n_false / quiet_years) if quiet_years > 0 else float("nan")

        # Frozen criteria (identical for every scorer and protocol version).
        c_lead = median_lead is not None and float(median_lead) >= MIN_MEDIAN_LEAD
        c_fa = np.isfinite(fa_per_quiet_year) and fa_per_quiet_year <= MAX_FALSE_ALARMS_PER_QUIET_YEAR
        c_lift = (ap_obs > pers_card["average_precision"]) and (ap_obs > ar1_card["average_precision"]) \
            and (card["roc_auc"] > pers_card["roc_auc"]) and (card["roc_auc"] > ar1_card["roc_auc"])
        c_ap = bool(np.isfinite(ap_obs) and ap_obs > base_rate)

        scorers_out[scorer_name] = {
            "card": card,
            "ap_permutation_p": p_value,
            "precision_at_alarm_ci95": [round(precision_ci[0], 4), round(precision_ci[1], 4)],
            "fa_per_quiet_year": round(float(fa_per_quiet_year), 3) if np.isfinite(fa_per_quiet_year) else None,
            "criteria": {
                "median_lead_ge_10": bool(c_lead),
                "fa_per_quiet_year_le_4": bool(c_fa),
                "beats_both_baselines_auc_and_ap": bool(c_lift),
                "ap_above_base_rate": c_ap,
            },
            "passed_pre_holm": bool(all([c_lead, c_fa, c_lift, c_ap])),
        }

    # 7. Episode-overlap context (reported, not a criterion).
    dates = eval_frame["Date"]
    overlap = {}
    for name in entry.get("episodes_covered", []):
        lo, hi = EPISODES[name]
        idx = np.flatnonzero((dates >= pd.Timestamp(lo)).to_numpy() & (dates <= pd.Timestamp(hi)).to_numpy())
        rel = idx[(idx >= offsets[0]) & (idx <= offsets[-1])] - offsets[0]
        rel = rel[(rel >= 0) & (rel < events.size)]
        overlap[name] = bool(events[rel].any()) if rel.size else False


    # Legacy top-level view = the TAN scorer, so v1/v2's published report
    # shape stays byte-stable; v3's report renders the scorer table too.
    tan = scorers_out["tan_frozen"]
    tan_card = tan["card"]
    out.update(
        status="evaluated",
        n_steps=int(events.size),
        base_rate=round(base_rate, 5),
        n_events=int(labelling.n_events),
        labelling_threshold=float(labelling.threshold),
        model=tan_card, persistence_baseline=pers_card, ar1_baseline=ar1_card,
        ap_permutation_p=tan["ap_permutation_p"],
        precision_at_alarm_ci95=tan["precision_at_alarm_ci95"],
        fa_per_quiet_year=tan["fa_per_quiet_year"],
        quiet_years=round(quiet_years, 2),
        criteria=tan["criteria"],
        alarm_quantile=alarm_q,
        scorers=scorers_out,
        episode_overlap=overlap,
        train_span=[str(train_frame['Date'].min().date()), str(train_frame['Date'].max().date())],
        eval_span=[str(dates.iloc[offsets[0]].date()), str(dates.iloc[offsets[-1]].date())],
        model_config=MODEL_CONFIG,
    )
    out["passed"] = tan["passed_pre_holm"]  # Holm adjustment applied in eval_phase

    # teardown before the next indicator
    del engine, trainer, risk_series, block
    gc.collect()
    return out


def eval_phase(proto: Dict[str, Any]) -> int:
    manifest_path = proto["data_dir"] / "manifest.json"
    report_dir: Path = proto["report_dir"]
    manifest = json.loads(manifest_path.read_text())
    results: Dict[str, Any] = {}
    for code in manifest["testable_family"]:
        entry = manifest["entries"][code]
        logger.info("=== evaluating %s ===", code)
        try:
            results[code] = _evaluate_indicator(code, entry, proto)
        except Exception as exc:  # noqa: BLE001 - an infrastructure failure is a recorded failure, not a silent skip
            logger.exception("%s: evaluation failed", code)
            results[code] = {"code": code, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:400]}
        logger.info("%s -> %s", code, results[code].get("status"))

    evaluated = {c: r for c, r in results.items() if r.get("status") == "evaluated"}
    # Holm-Bonferroni across EVERY declared scorer-indicator pair: pooling
    # only one scorer would understate the multiplicity the protocol itself
    # introduces. For single-scorer protocols (v1/v2) the pool is unchanged.
    pvals: Dict[str, float] = {}
    for code, r in evaluated.items():
        for scorer_name, scorer_result in (r.get("scorers") or {"tan_frozen": r}).items():
            p_value = scorer_result.get("ap_permutation_p")
            if p_value is not None and np.isfinite(p_value):
                pvals[f"{code}::{scorer_name}"] = float(p_value)
    holm = _holm(pvals, HOLM_ALPHA) if pvals else {}
    for code, r in evaluated.items():
        scorers = r.get("scorers") or {"tan_frozen": r}
        any_pass = False
        for scorer_name, scorer_result in scorers.items():
            survives = bool(holm.get(f"{code}::{scorer_name}", False))
            scorer_result["ap_survives_holm_bonferroni"] = survives
            if "passed_pre_holm" in scorer_result:
                scorer_result["passed"] = bool(scorer_result["passed_pre_holm"] and survives)
            if scorer_result.get("passed"):
                any_pass = True
        tan = scorers.get("tan_frozen", {})
        r["ap_survives_holm_bonferroni"] = tan.get("ap_survives_holm_bonferroni")
        # An indicator passes when any of its declared scorers passes all
        # four criteria with a Holm-surviving AP (declared in the protocol;
        # for single-scorer protocols this is exactly the v1/v2 rule).
        r["passed"] = any_pass

    passed = sorted(c for c, r in evaluated.items() if r.get("passed"))
    tested = sorted(evaluated)
    enough_tested = len(tested) >= MIN_TESTABLE_FAMILY
    family_verdict = {
        "tested": tested,
        "passed": passed,
        "n_tested": len(tested),
        "n_passed": len(passed),
        "min_testable_family": MIN_TESTABLE_FAMILY,
        "family_rule": (
            f"at least half of the tested family passes all criteria (Holm-adjusted AP "
            f"included), AND at least {MIN_TESTABLE_FAMILY} indicators were testable -- "
            "a claim graded on fewer than that is a claim graded on an anecdote"
        ),
        "family_claim_warranted": bool(enough_tested and tested and len(passed) * 2 >= len(tested)),
    }
    if not enough_tested:
        family_verdict["insufficient_testable_family"] = (
            f"only {len(tested)} indicator(s) survived the declared data-availability rules; "
            "per-indicator results below are still reported, but no system-level claim can be made"
        )

    report = {
        "protocol": proto["name"],
        "prereg_tag": proto["tag"],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runner": "scripts/run_preregistered_eval.py",
        "deviations": [
            f"{proto['name']} runs in-process rather than via the Celery job queue (protocol section 'Execution'); the computation mirrors run_backtest's event idiom",
            "chronological holdout (train <= 2006, evaluate 2007-2024) rather than CPCV; CPCV is a declared future upgrade",
        ],
        "constants": {
            "eval_window": [str(EVAL_START.date()), str(EVAL_END.date())],
            "quantile": QUANTILE, "horizon": HORIZON, "min_duration": MIN_DURATION,
            "alarm_quantile": proto.get("alarm_quantile", ALARM_QUANTILE), "max_lead": MAX_LEAD,
            "scorers": list(proto.get("scorers", ("tan_frozen",))),
            "perm_iterations": PERM_ITERATIONS, "perm_seed": PERM_SEED, "holm_alpha": HOLM_ALPHA,
            "criteria": {"min_median_lead": MIN_MEDIAN_LEAD,
                          "max_fa_per_quiet_year": MAX_FALSE_ALARMS_PER_QUIET_YEAR},
        },
        "manifest": manifest["entries"],
        "results": results,
        "family_verdict": family_verdict,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (report_dir / "report.md").write_text(_render_markdown(report))
    logger.info("report written to %s", report_dir)
    print(_render_markdown(report))
    return 0


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        f"# Pre-registered early-warning evaluation — run report ({report['protocol']})",
        "",
        f"*Run at {report['run_at']} against tag `{report['prereg_tag']}`. Single-run rule: these numbers are the run.*",
        "",
        "## Family verdict",
        "",
        f"- Tested: **{report['family_verdict']['n_tested']}** indicator(s): {', '.join(report['family_verdict']['tested']) or 'none'}",
        f"- Passed all frozen criteria (Holm-adjusted): **{report['family_verdict']['n_passed']}** — {', '.join(report['family_verdict']['passed']) or 'none'}",
        f"- Family rule: {report['family_verdict']['family_rule']}",
        f"- **System-level 'demonstrated early-warning' claim warranted: {'YES' if report['family_verdict']['family_claim_warranted'] else 'NO'}**",
    ]
    if report["family_verdict"].get("insufficient_testable_family"):
        lines.append(f"- ⚠️ {report['family_verdict']['insufficient_testable_family']}")
    lines += [
        "",
        "## Per-indicator results",
        "",
        "| code | status | events | base rate | AUC | AP | AP p (perm) | median lead | FA/quiet-yr | beats baselines | passed |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for code, r in sorted(report["results"].items()):
        if r.get("status") != "evaluated":
            lines.append(f"| `{code}` | {r.get('status')} ({r.get('skip_reason') or r.get('error', '')}) | – | – | – | – | – | – | – | – | – |")
            continue
        scorers = r.get("scorers") or {"tan_frozen": r}
        multi = len(scorers) > 1
        for scorer_name, sres in scorers.items():
            label = f"`{code}`" + (f" · {scorer_name}" if multi else "")
            card = sres.get("card") or sres.get("model")
            if card is None:
                lines.append(f"| {label} | scorer skipped ({sres.get('skipped', '?')}) | – | – | – | – | – | – | – | – | – |")
                continue
            crit = sres["criteria"]
            p_val = sres.get("ap_permutation_p", float("nan"))
            lt = card["lead_time"].get("median_lead")
            scorer_passed = sres.get("passed", sres.get("passed_pre_holm"))
            lines.append(
                f"| {label} | evaluated | {r['n_events']} | {r['base_rate']:.3f} "
                f"| {card['roc_auc']:.3f} | {card['average_precision']:.3f} "
                f"| {p_val:.4f} | {lt if lt is not None else 'n/a'} "
                f"| {sres.get('fa_per_quiet_year')} | {'yes' if crit['beats_both_baselines_auc_and_ap'] else 'no'} "
                f"| {'PASS' if scorer_passed else 'fail'} |"
            )
        if multi:
            lines.append(
                f"| `{code}` — **indicator verdict** | {'PASS' if r.get('passed') else 'fail'} "
                "(any declared scorer, Holm-adjusted) | | | | | | | | | |"
            )
    lines += ["", "## Criteria (frozen pre-run; identical thresholds in every protocol version)", "",
              f"0. Alarm rule and scorers are declared per protocol version: this run used alarm quantile "
              f"{report['constants']['alarm_quantile']} and scorer(s) {', '.join(report['constants'].get('scorers', ['tan_frozen']))}",
              f"1. median lead >= {MIN_MEDIAN_LEAD} business days (max_lead {MAX_LEAD}, earliest-alarm convention)",
              f"2. false alarms <= {MAX_FALSE_ALARMS_PER_QUIET_YEAR:.0f} per quiet year (an alarm simultaneous with an event counts as false: it warned nobody)",
              "3. AUC and AP both strictly above the persistence AND the AR(1) baseline on the identical grid",
              f"4. AP above the event base rate, with a permutation p-value ({PERM_ITERATIONS} shuffles, seed {PERM_SEED}) surviving Holm-Bonferroni at {HOLM_ALPHA} across the tested family",
              "", "## Skips and exclusions (data availability or licence, applied before any metric)", ""]
    for code, entry in sorted(report["manifest"].items()):
        status = entry.get("status")
        if status in ("skipped", "excluded"):
            lines.append(f"- `{code}`: **{status}** — {entry.get('skip_reason') or ''} {entry.get('reason') or entry.get('detail') or ''}".rstrip())
    lines += ["", "## Deviations (declared in the protocol)", ""]
    for d in report["deviations"]:
        lines.append(f"- {d}")
    lines += ["", "## Data provenance", "",
              "Every series was fetched through the platform's own FRED plugin,",
              "licence-screened where the protocol requires it, certified by the real quality gate",
              "before scoring, and recorded in the protocol's `manifest.json` with endpoint (API key",
              "redacted), fetch timestamp, SHA-256, row counts, measured frequency, coverage and the",
              "series' own licence lines. Labels come from `label_events` on raw series; the model",
              "never saw the evaluation window during training.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", choices=sorted(PROTOCOLS), default="v1",
                        help="which tagged protocol to execute (default: v1)")
    parser.add_argument("--fetch", action="store_true", help="phase 1: screen, fetch, validate, manifest")
    parser.add_argument("--eval", action="store_true", help="phase 2: run the frozen evaluation once")
    args = parser.parse_args()
    proto = PROTOCOLS[args.protocol]
    if args.fetch:
        return fetch_phase(proto)
    if args.eval:
        return eval_phase(proto)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
