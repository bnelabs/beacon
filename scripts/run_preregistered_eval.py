#!/usr/bin/env python
"""Pre-registered early-warning evaluation runner (protocol v1).

This script EXECUTES the protocol frozen in ``docs/prereg/early_warning_v1.md``
and ``configs/event_eval_v1.yaml``. It is the glue step 3 of
``docs/probes/event_target_proposal.md``; the proposal is the rationale, the
protocol files are the contract, and this file is the machine that honours
them.

Discipline encoded here (and enforced by the protocol's single-run rule):

* every number in this file -- windows, quantiles, thresholds, model config,
  permutation seed -- is a protocol constant duplicated from the YAML. If a
  value here disagrees with the YAML, that is a bug; the YAML and the tag win.
* skips are data-availability decisions applied BEFORE any metric is
  computed (fetch failure, declared coverage floor, quality gate). Nothing
  is skipped because of a result.
* labels never touch features: ``label_events`` sees the raw series; the
  model sees windows that end before the labelled step; the split between
  training data (<= 2006) and the evaluation window (2007+) is chronological.
* scores are sign-adjusted by the registry's stress direction so "higher =
  more stress" for every indicator, and labels are joined to scores through
  ``row_offset`` (the RiskSeriesResult contract), never by truncation.
* the run is sequential per indicator with small models and explicit
  teardown, so it fits a 2-CPU / <1GB host: pre-registration is about the
  rules, not about compute.

Phases:
    --fetch   download the declared family through the platform's own FRED
              plugin (keyless fallback), validate, hash, apply the coverage
              rules, write data/prereg/manifest.json
    --eval    certify (quality gate), train, label, score, apply the frozen
              criteria, write the report under docs/prereg/runs/

Deviation, stated because the protocol states it: v1 runs in-process rather
than through the Celery job queue. The computation mirrors ``run_backtest``'s
event idiom (same labeller, same metric functions, same alarm rule) with the
alignment and direction corrections that idiom received in the same change.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import math
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

DATA_DIR = REPO / "data" / "prereg"
REPORT_DIR = REPO / "docs" / "prereg" / "runs" / "early_warning_v1"
MANIFEST_PATH = DATA_DIR / "manifest.json"

# --------------------------------------------------------------------------
# Protocol constants (mirrors configs/event_eval_v1.yaml; the tag wins)
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

# Criteria (frozen; the proposal's section 4 defaults, owner-approved)
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

# Family = every code in the semantics registry, with a declared disposition
# per code. Exclusions are decisions recorded before any data was fetched.
FAMILY: Dict[str, Dict[str, Any]] = {
    "FRED_STLFSI4":      {"source": "fred", "series_id": "STLFSI4"},
    "FRED_KCFSI":        {"source": "fred", "series_id": "KCFSI"},
    "FRED_SOFR":         {"source": "fred", "series_id": "SOFR"},
    "FRED_BAMLH0A0HYM2": {"source": "fred", "series_id": "BAMLH0A0HYM2"},
    "FRED_T10Y2Y":       {"source": "fred", "series_id": "T10Y2Y"},
    # One declared keyless attempt at FRED id "CISS"; a 404 is recorded as a
    # fetch skip, and no substitute source is improvised.
    "ECB_CISS":          {"source": "fred", "series_id": "CISS"},
    "FRED_RRPONTSYD":    {"excluded": "owner decision: the registry itself flags its direction as a funding-sense judgement (proposal section 6)"},
    "HQLA_LEVEL":        {"excluded": "operator-reported series; no public source in the evaluation environment"},
    "LCR_RATIO":         {"excluded": "operator-reported series; no public source in the evaluation environment"},
    "NSFR_RATIO":        {"excluded": "operator-reported series; no public source in the evaluation environment"},
    "BANK_EQUITY_INDEX": {"excluded": "operator-reported series; no public source in the evaluation environment"},
    "FX_SWAP_BASIS":     {"excluded": "operator-reported series; no public source in the evaluation environment"},
    "CDS_PREMIUM":       {"excluded": "operator-reported series; no public source in the evaluation environment"},
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


def fetch_phase() -> int:
    from backend.plugins.fred_plugin import FREDPlugin

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    plugin = FREDPlugin(config={})  # no key: the plugin's keyless fredgraph.csv path
    manifest: Dict[str, Any] = {
        "protocol": "early_warning_v1",
        "fetched_at": RUN_STARTED_AT,
        "eval_window": [str(EVAL_START.date()), str(EVAL_END.date())],
        "entries": {},
    }
    eval_busdays = int(np.busday_count(EVAL_START.date(), (EVAL_END + pd.Timedelta(days=1)).date()))

    for code, spec in FAMILY.items():
        if "excluded" in spec:
            manifest["entries"][code] = {"status": "excluded", "reason": spec["excluded"]}
            continue

        series_id = spec["series_id"]
        entry: Dict[str, Any] = {
            "status": "pending",
            "source": "fred_plugin (keyless fredgraph.csv)",
            "series_id": series_id,
            "endpoint": f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}",
        }
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

        csv_path = DATA_DIR / f"{code}.csv"
        frame.to_csv(csv_path, index=False)

        eval_rows = frame[(frame["Date"] >= EVAL_START) & (frame["Date"] <= EVAL_END)]
        coverage_frac = float(len(eval_rows)) / eval_busdays if eval_busdays else 0.0

        # Frequency is a data-availability fact, measured before any metric:
        # the protocol's step is one business day (horizon 21 ~ one month), so
        # weekly/monthly series are skipped rather than silently resampled --
        # a resampling rule would be a new researcher degree of freedom
        # invented mid-run. Resampling design is declared v2 work.
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
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    logger.info("manifest written: %d testable, %d skipped, %d excluded",
                len(testable),
                sum(1 for e in manifest["entries"].values() if e.get("status") == "skipped"),
                sum(1 for e in manifest["entries"].values() if e.get("status") == "excluded"))
    return 0


# --------------------------------------------------------------------------
# Phase 2 helpers
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


def _evaluate_indicator(code: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    import torch

    from backend.modules.data.event_labeller import EventDefinition, label_events
    from backend.modules.data.quality_gate import QualityGate
    from backend.modules.data.semantics import event_direction, stress_direction
    from backend.modules.engine.event_metrics import (
        average_precision,
        false_alarm_stats,
        lead_time_stats,
        roc_auc,
    )
    from backend.modules.engine.model_io import safe_torch_load, safe_torch_save
    from backend.modules.engine.prediction_engine import RealPredictionEngine
    from backend.modules.engine.trainer import ModelTrainer

    out: Dict[str, Any] = {"code": code, "direction": event_direction(code)}
    direction_sign = 1.0 if stress_direction(code) >= 0 else -1.0

    frame = pd.read_csv(REPO / entry["csv"], parse_dates=["Date"])
    frame = frame.sort_values("Date").reset_index(drop=True)
    train_frame = frame[frame["Date"] <= TRAIN_END][["Date", "Value"]].reset_index(drop=True)
    eval_frame = frame[(frame["Date"] >= EVAL_START) & (frame["Date"] <= EVAL_END)][["Date", "Value"]].reset_index(drop=True)
    out["rows_train"], out["rows_eval"] = int(len(train_frame)), int(len(eval_frame))

    # 1. Certification: the real quality gate, on the evaluation payload.
    gate = QualityGate()
    attestation = gate.evaluate({code: eval_frame}, job_id=f"prereg-ew-v1-{code}")
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

    # 2. Train the frozen small model on the pre-2007 span only.
    workdir = DATA_DIR / "work" / code
    workdir.mkdir(parents=True, exist_ok=True)
    split_at = int(len(train_frame) * 0.8)
    trainer = ModelTrainer(model_type="temporal_attention", device=torch.device("cpu"), config=dict(MODEL_CONFIG))
    torch.manual_seed(11)  # frozen training seed; member of the protocol, not a tuned value
    metrics = trainer.train(
        train_df=train_frame.iloc[:split_at],
        val_df=train_frame.iloc[split_at:],
        test_df=eval_frame,
        output_dir=str(workdir),
    )
    checkpoint_path = Path(metrics.model_path)

    # Attach the training-span normalisation so the engine scores in the
    # space the model was trained in, not in payload-derived statistics.
    train_values = pd.to_numeric(train_frame["Value"], errors="coerce").to_numpy(dtype=float)
    finite = train_values[np.isfinite(train_values)]
    checkpoint = safe_torch_load(str(checkpoint_path))
    checkpoint["source_stats"] = {code: {"mean": float(finite.mean()), "std": float(finite.std())}}
    checkpoint["sources"] = [code]
    safe_torch_save(checkpoint, checkpoint_path)

    # 3. Out-of-sample per-timestep risk series over the evaluation window.
    engine = RealPredictionEngine(str(checkpoint_path), torch.device("cpu"),
                                  {"sequence_length": MODEL_CONFIG["sequence_length"], "job_id": f"prereg-{code}"})
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

    def _score_card(sc: np.ndarray) -> Dict[str, Any]:
        alarms = sc >= float(np.quantile(sc, ALARM_QUANTILE))
        lead = lead_time_stats(events, alarms, max_lead=MAX_LEAD)
        fa = false_alarm_stats(alarms, events, horizon=HORIZON)
        return {
            "roc_auc": roc_auc(events, sc),
            "average_precision": average_precision(events, sc),
            "lead_time": lead,
            "false_alarms": fa,
            "n_alarms": int(alarms.sum()),
        }

    model_card = _score_card(scores)
    pers_card = _score_card(persistence_scores)
    ar1_card = _score_card(ar1_scores)

    base_rate = float(events.mean())
    ap_obs = model_card["average_precision"]
    p_value = _permutation_ap_pvalue(events.astype(bool), scores, ap_obs) if np.isfinite(ap_obs) else 1.0

    n_true = int(model_card["false_alarms"].get("n_true_alarms", 0))
    n_false = int(model_card["false_alarms"].get("n_false_alarms", 0))
    quiet_years = float((events.size - events.sum())) / BUSINESS_DAYS_PER_YEAR
    precision_ci = _wilson_ci(n_true, n_true + n_false)
    median_lead = model_card["lead_time"].get("median_lead")
    fa_per_quiet_year = (n_false / quiet_years) if quiet_years > 0 else float("nan")

    # 6. Frozen criteria.
    c_lead = median_lead is not None and float(median_lead) >= MIN_MEDIAN_LEAD
    c_fa = np.isfinite(fa_per_quiet_year) and fa_per_quiet_year <= MAX_FALSE_ALARMS_PER_QUIET_YEAR
    c_lift = (ap_obs > pers_card["average_precision"]) and (ap_obs > ar1_card["average_precision"]) \
        and (model_card["roc_auc"] > pers_card["roc_auc"]) and (model_card["roc_auc"] > ar1_card["roc_auc"])
    c_ap = bool(np.isfinite(ap_obs) and ap_obs > base_rate)

    # 7. Episode-overlap context (reported, not a criterion).
    dates = eval_frame["Date"]
    overlap = {}
    for name in entry.get("episodes_covered", []):
        lo, hi = EPISODES[name]
        idx = np.flatnonzero((dates >= pd.Timestamp(lo)).to_numpy() & (dates <= pd.Timestamp(hi)).to_numpy())
        rel = idx[(idx >= offsets[0]) & (idx <= offsets[-1])] - offsets[0]
        rel = rel[(rel >= 0) & (rel < events.size)]
        overlap[name] = bool(events[rel].any()) if rel.size else False

    out.update(
        status="evaluated",
        n_steps=int(events.size),
        base_rate=round(base_rate, 5),
        n_events=int(labelling.n_events),
        labelling_threshold=float(labelling.threshold),
        model=model_card, persistence_baseline=pers_card, ar1_baseline=ar1_card,
        ap_permutation_p=p_value,
        precision_at_alarm_ci95=[round(precision_ci[0], 4), round(precision_ci[1], 4)],
        fa_per_quiet_year=round(float(fa_per_quiet_year), 3) if np.isfinite(fa_per_quiet_year) else None,
        quiet_years=round(quiet_years, 2),
        criteria={
            "median_lead_ge_10": bool(c_lead),
            "fa_per_quiet_year_le_4": bool(c_fa),
            "beats_both_baselines_auc_and_ap": bool(c_lift),
            "ap_above_base_rate": c_ap,
        },
        episode_overlap=overlap,
        train_span=[str(train_frame['Date'].min().date()), str(train_frame['Date'].max().date())],
        eval_span=[str(dates.iloc[offsets[0]].date()), str(dates.iloc[offsets[-1]].date())],
        model_config=MODEL_CONFIG,
    )
    out["passed"] = all([c_lead, c_fa, c_lift, c_ap])

    # teardown before the next indicator
    del engine, trainer, risk_series, block
    gc.collect()
    return out


def eval_phase() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text())
    results: Dict[str, Any] = {}
    for code in manifest["testable_family"]:
        entry = manifest["entries"][code]
        logger.info("=== evaluating %s ===", code)
        try:
            results[code] = _evaluate_indicator(code, entry)
        except Exception as exc:  # noqa: BLE001 - an infrastructure failure is a recorded failure, not a silent skip
            logger.exception("%s: evaluation failed", code)
            results[code] = {"code": code, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:400]}
        logger.info("%s -> %s", code, results[code].get("status"))

    evaluated = {c: r for c, r in results.items() if r.get("status") == "evaluated"}
    pvals = {c: float(r["ap_permutation_p"]) for c, r in evaluated.items() if np.isfinite(r.get("ap_permutation_p", np.nan))}
    holm = _holm(pvals, HOLM_ALPHA) if pvals else {}
    for code, survives in holm.items():
        results[code]["ap_survives_holm_bonferroni"] = survives
        # criterion 4 is AP > base rate AND family-wise significance
        results[code]["passed"] = bool(
            results[code]["passed"] and survives
        ) if "passed" in results[code] else False

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
        "protocol": "early_warning_v1",
        "prereg_tag": "prereg-early-warning-v1",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runner": "scripts/run_preregistered_eval.py",
        "deviations": [
            "v1 runs in-process rather than via the Celery job queue (protocol section 'Execution'); the computation mirrors run_backtest's event idiom",
            "chronological holdout (train <= 2006, evaluate 2007-2024) rather than CPCV; CPCV is the declared v2 upgrade",
        ],
        "constants": {
            "eval_window": [str(EVAL_START.date()), str(EVAL_END.date())],
            "quantile": QUANTILE, "horizon": HORIZON, "min_duration": MIN_DURATION,
            "alarm_quantile": ALARM_QUANTILE, "max_lead": MAX_LEAD,
            "perm_iterations": PERM_ITERATIONS, "perm_seed": PERM_SEED, "holm_alpha": HOLM_ALPHA,
            "criteria": {"min_median_lead": MIN_MEDIAN_LEAD,
                          "max_fa_per_quiet_year": MAX_FALSE_ALARMS_PER_QUIET_YEAR},
        },
        "manifest": manifest["entries"],
        "results": results,
        "family_verdict": family_verdict,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (REPORT_DIR / "report.md").write_text(_render_markdown(report))
    logger.info("report written to %s", REPORT_DIR)
    print(_render_markdown(report))
    return 0


def _render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Pre-registered early-warning evaluation — run report (protocol v1)",
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
        crit = r["criteria"]
        lt = r["model"]["lead_time"].get("median_lead")
        lines.append(
            f"| `{code}` | evaluated | {r['n_events']} | {r['base_rate']:.3f} "
            f"| {r['model']['roc_auc']:.3f} | {r['model']['average_precision']:.3f} "
            f"| {r['ap_permutation_p']:.4f} | {lt if lt is not None else 'n/a'} "
            f"| {r['fa_per_quiet_year']} | {'yes' if crit['beats_both_baselines_auc_and_ap'] else 'no'} "
            f"| {'PASS' if r.get('passed') else 'fail'} |"
        )
    lines += ["", "## Criteria (frozen pre-run)", "",
              f"1. median lead >= {MIN_MEDIAN_LEAD} business days (max_lead {MAX_LEAD}, earliest-alarm convention)",
              f"2. false alarms <= {MAX_FALSE_ALARMS_PER_QUIET_YEAR:.0f} per quiet year (an alarm simultaneous with an event counts as false: it warned nobody)",
              "3. AUC and AP both strictly above the persistence AND the AR(1) baseline on the identical grid",
              f"4. AP above the event base rate, with a permutation p-value ({PERM_ITERATIONS} shuffles, seed {PERM_SEED}) surviving Holm-Bonferroni at {HOLM_ALPHA} across the tested family",
              "", "## Skips and exclusions (data availability, applied before any metric)", ""]
    for code, entry in sorted(report["manifest"].items()):
        status = entry.get("status")
        if status in ("skipped", "excluded"):
            lines.append(f"- `{code}`: **{status}** — {entry.get('skip_reason') or ''} {entry.get('reason') or entry.get('detail') or ''}".rstrip())
    lines += ["", "## Deviations (declared in the protocol)", ""]
    for d in report["deviations"]:
        lines.append(f"- {d}")
    lines += ["", "## Data provenance", "",
              "Every series was fetched through the platform's own FRED plugin (keyless `fredgraph.csv`),",
              "certified by the real quality gate before scoring, and recorded in `data/prereg/manifest.json`",
              "with URL, fetch timestamp, SHA-256, row counts and coverage. Labels come from `label_events`",
              "on raw series; the model never saw the evaluation window during training.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="phase 1: fetch, validate, manifest")
    parser.add_argument("--eval", action="store_true", help="phase 2: run the frozen evaluation once")
    args = parser.parse_args()
    if args.fetch:
        return fetch_phase()
    if args.eval:
        return eval_phase()
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
