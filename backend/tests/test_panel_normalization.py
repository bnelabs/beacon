"""Panel feeds are standardized per entity, not per feed.

``MultiScaleTrainer`` groups its windows by ``series_id`` -- the per-entity
series the DATA formatter builds for panel feeds such as AI4Risk's
bank-to-bank edges -- but until this round it keyed its **normalization
statistics and denormalization** by ``source_code``, the feed. For a feed with
more than one entity, every entity after the first overwrote the previous
one's statistics (``source_stats[source] = ...`` inside the group loop), so:

* each entity was standardized with one entity's mean and standard deviation;
* an entity whose scale is far from that winner collapsed to a constant, which
  makes its targets identical and its loss trivially low;
* reported ``actual``/``predicted`` rows, MAE, RMSE and R-squared -- and
  ``per_source_metrics`` written into ``Job.result`` -- were denormalized
  through that same single scale, so a 100-scale entity was reported as if it
  lived at 10^6;
* the checkpoint persisted the same feed-keyed map, so inference applied it to
  every entity of the feed.

These tests compose the frame the formatter actually produces (``source_code``
*and* ``series_id``) and assert the invariant the fix installs: **the grain of
the statistics matches the grain of the grouping, and wherever the two cannot
be made to agree the run says so instead of inventing a number.** Synthetic
values: this verifies machinery, never a risk claim. Skipped when torch is absent.
"""

from __future__ import annotations

import os

os.environ.setdefault("USE_SQLITE", "true")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

torch = pytest.importorskip("torch")

from backend.modules.engine.model_io import safe_torch_load  # noqa: E402
from backend.modules.engine.model_io import safe_torch_save  # noqa: E402
from backend.modules.engine.multi_scale_trainer import (  # noqa: E402
    MultiSourceDataset,
    MultiScaleTemporalAttentionModel,
    MultiScaleTrainer,
)
from backend.modules.engine.orchestrator import EngineOrchestrator  # noqa: E402
from backend.modules.engine.prediction_engine import RealPredictionEngine  # noqa: E402

FEED = "AI4RISK_EDGE"
ENTITIES = ("ENT_ALPHA", "ENT_BETA")
SERIES_KEYS = tuple(f"{FEED}::{entity}" for entity in ENTITIES)

# Two entities of one feed whose scales differ by four orders of magnitude --
# the shape a bank-capital panel and a small-exposure edge produce.
LEVELS = {"ENT_ALPHA": 100.0, "ENT_BETA": 1_000_000.0}
SPREADS = {"ENT_ALPHA": 6.0, "ENT_BETA": 40_000.0}

ROWS = 40
SEQUENCE_LENGTH = 6


def _panel_frame(rows: int = ROWS) -> pd.DataFrame:
    """A panel feed exactly like ``format_panel_data`` concatenates it."""
    rng = np.random.default_rng(21)
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    frames = []
    for entity in ENTITIES:
        values = LEVELS[entity] + rng.normal(0.0, SPREADS[entity], rows)
        frames.append(pd.DataFrame({
            "Date": dates,
            "date": dates,
            "Close": values,
            "Value": values,
            "source_code": FEED,
            "series_id": f"{FEED}::{entity}",
            "entity_id": entity,
        }))
    return pd.concat(frames, ignore_index=True)


def _feed_frame(rows: int = ROWS) -> pd.DataFrame:
    """The control: a frame with no panel identity keeps its feed grain."""
    rng = np.random.default_rng(29)
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    frames = []
    for index, source in enumerate(("SRC_A", "SRC_B")):
        values = (index + 1) * 50.0 + rng.normal(0.0, 4.0, rows)
        frames.append(pd.DataFrame({
            "Date": dates, "date": dates, "Close": values, "Value": values,
            "source_code": source,
        }))
    return pd.concat(frames, ignore_index=True)


def _config(epochs: int = 1) -> dict:
    return {
        "epochs": epochs,
        "sequence_length": SEQUENCE_LENGTH,
        "batch_size": 8,
        "d_model": 8,
        "nhead": 2,
        "num_layers": 1,
        "dropout": 0.0,
    }


def _split_by_date(df: pd.DataFrame, train_frac: float = 0.7, val_frac: float = 0.15):
    dates = df["Date"]
    dmin, dmax = dates.min(), dates.max()
    t1 = dmin + (dmax - dmin) * train_frac
    t2 = dmin + (dmax - dmin) * (train_frac + val_frac)
    return df[dates <= t1], df[(dates > t1) & (dates <= t2)], df[dates > t2]


def _train_panel(output_dir: str):
    train_df, val_df, test_df = _split_by_date(_panel_frame())
    trainer = MultiScaleTrainer(
        model_type="temporal_attention",
        device=torch.device("cpu"),
        config=_config(),
    )
    metrics = trainer.train(train_df, val_df, test_df, output_dir)
    return metrics, trainer


@pytest.fixture(scope="module")
def panel_run(tmp_path_factory):
    """One tiny end-to-end training run on a panel frame, shared by the tests."""
    output_dir = tmp_path_factory.mktemp("panel-run")
    metrics, trainer = _train_panel(str(output_dir))
    return metrics, trainer, str(output_dir)


class TestStatisticsAreKeyedByTheSeriesTheyStandardize:
    def test_panel_statistics_are_keyed_by_series_id(self):
        ds = MultiSourceDataset(_panel_frame(), sequence_length=SEQUENCE_LENGTH)
        assert ds.stats_grain == "series"
        assert set(ds.source_stats) == set(SERIES_KEYS)
        # The model's source embedding stays feed-grain: one embedding for the
        # feed, two normalization maps for its entities.
        assert list(ds.sources) == [FEED]
        assert ds.source_to_id == {FEED: 0}

    def test_each_series_statistics_match_its_own_observed_scale(self):
        frame = _panel_frame()
        ds = MultiSourceDataset(frame, sequence_length=SEQUENCE_LENGTH)
        for entity in ENTITIES:
            observed = pd.to_numeric(
                frame.loc[frame["entity_id"] == entity, "Close"], errors="coerce"
            ).to_numpy(dtype=float)
            stats = ds.source_stats[f"{FEED}::{entity}"]
            assert stats["mean"] == pytest.approx(float(observed.mean()), abs=1e-6)
            # The std carries the trainer's 1e-8 regularizer for a degenerate
            # series, so the comparison is absolute rather than relative.
            assert stats["std"] == pytest.approx(float(observed.std()), abs=1e-6)
        # The two maps must not be the same number: sharing one is the defect.
        assert abs(
            ds.source_stats[SERIES_KEYS[0]]["mean"] - ds.source_stats[SERIES_KEYS[1]]["mean"]
        ) > 1e5

    def test_feed_grained_frames_keep_feed_grain_statistics(self):
        ds = MultiSourceDataset(_feed_frame(), sequence_length=SEQUENCE_LENGTH)
        assert ds.stats_grain == "feed"
        assert set(ds.source_stats) == {"SRC_A", "SRC_B"}


class TestNoSeriesIsStandardizedInAnotherEntitysSpace:
    def test_every_target_denormalizes_back_to_its_own_series(self):
        """A target is the next observation of its own series, so denormalizing
        it must land on a raw value of that series -- not on a number from
        another entity's scale."""
        frame = _panel_frame()
        ds = MultiSourceDataset(frame, sequence_length=SEQUENCE_LENGTH)
        raw_by_series = {
            key: set(
                np.round(
                    pd.to_numeric(
                        frame.loc[frame["series_id"] == key, "Close"], errors="coerce"
                    ).to_numpy(dtype=float),
                    decimals=6,
                ).tolist()
            )
            for key in SERIES_KEYS
        }
        denormalized = ds.denormalize(
            np.asarray(ds.targets, dtype=float),
            series_ids=np.asarray(ds.series_ids, dtype=int),
        )
        for value, series_index in zip(denormalized, ds.series_ids):
            key = ds.series_labels[int(series_index)]
            assert round(float(value), 6) in raw_by_series[key], (
                f"target {value!r} does not resolve to an observation of {key}"
            )

    def test_a_small_entity_is_not_collapsed_by_a_larger_one(self):
        """With a shared scale the 100-scale entity's windows were a constant
        (observed spread 0.16 in standardized units, mean -19.9)."""
        ds = MultiSourceDataset(_panel_frame(), sequence_length=SEQUENCE_LENGTH)
        for index, key in enumerate(SERIES_KEYS):
            mask = np.asarray(ds.series_ids) == index
            assert mask.any(), f"no windows kept for {key}"
            window_spread = float(np.ptp(ds.sequences[mask]))
            target_spread = float(np.ptp(np.asarray(ds.targets)[mask]))
            assert window_spread > 1.0, f"{key} collapsed to a constant window space"
            assert target_spread > 1.0, f"{key} collapsed to a constant target"
            assert float(np.max(np.abs(ds.sequences[mask]))) < 10.0, (
                f"{key} is standardized in another entity's space"
            )


class TestReportedMetricsUseTheSeriesGrain:
    def test_predictions_are_denormalized_at_the_series_grain(self, panel_run):
        _, _, output_dir = panel_run
        predictions = pd.read_csv(os.path.join(output_dir, "predictions.csv"))
        assert "series" in predictions.columns
        for entity in ENTITIES:
            rows = predictions[predictions["series"] == f"{FEED}::{entity}"]
            assert not rows.empty, f"no predictions attributed to {entity}"
            level = LEVELS[entity]
            # The reported actuals must live in the entity's own scale. Under
            # the defect both entities were denormalized through the 10^6 map.
            assert np.max(np.abs(rows["actual"].to_numpy(dtype=float))) < level * 10
            if entity == "ENT_ALPHA":
                assert np.max(np.abs(rows["actual"].to_numpy(dtype=float))) < 1e4
            else:
                assert np.max(np.abs(rows["actual"].to_numpy(dtype=float))) > 1e5

    def test_metrics_name_each_entity_separately(self, panel_run):
        metrics, _, _ = panel_run
        assert set(metrics.per_series_metrics) == set(SERIES_KEYS)
        for key, block in metrics.per_series_metrics.items():
            assert np.isfinite(block["mae"])
        # A feed-level aggregate is kept, but it no longer stands in for the
        # entities inside it.
        assert FEED in metrics.per_source_metrics

    def test_training_history_records_the_grain(self, panel_run):
        _, _, output_dir = panel_run
        import json

        history = json.load(open(os.path.join(output_dir, "training_history.json")))
        assert set(history["per_series_metrics"]) == set(SERIES_KEYS)


class TestCheckpointManifestCarriesTheGrain:
    def test_checkpoint_records_the_grain_it_used(self, panel_run):
        _, _, output_dir = panel_run
        checkpoint = safe_torch_load(os.path.join(output_dir, "best_model.pt"))
        assert checkpoint["stats_grain"] == "series"
        assert set(checkpoint["source_stats"]) == set(SERIES_KEYS)
        assert list(checkpoint["sources"]) == [FEED]
        assert set(checkpoint["series_ids"]) == set(SERIES_KEYS)

    def test_feed_grained_checkpoint_records_feed_grain(self, tmp_path):
        train_df, val_df, test_df = _split_by_date(_feed_frame())
        trainer = MultiScaleTrainer(
            model_type="temporal_attention",
            device=torch.device("cpu"),
            config=_config(),
        )
        trainer.train(train_df, val_df, test_df, str(tmp_path))
        checkpoint = safe_torch_load(str(tmp_path / "best_model.pt"))
        assert checkpoint["stats_grain"] == "feed"
        assert set(checkpoint["source_stats"]) == {"SRC_A", "SRC_B"}


class TestInferenceHonoursTheRecordedGrain:
    """``EngineOrchestrator._predict`` groups by ``series_id`` and looks its
    statistics up by ``source_code``; after the fix the lookup grain is the one
    the checkpoint says it used, and a mismatch is reported rather than hidden."""

    @staticmethod
    def _legacy_checkpoint(output_dir, job_id: str) -> str:
        """A pre-fix manifest: statistics keyed by feed, no ``stats_grain``."""
        torch.manual_seed(5)
        model = MultiScaleTemporalAttentionModel(
            num_sources=1,
            sequence_length=SEQUENCE_LENGTH,
            d_model=8,
            nhead=2,
            num_layers=1,
            dropout=0.0,
        )
        path = os.path.join(output_dir, job_id, "best_model.pt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        safe_torch_save(
            {
                "model_state_dict": model.state_dict(),
                "config": {
                    "model": "temporal_attention",
                    "sequence_length": SEQUENCE_LENGTH,
                    "d_model": 8, "nhead": 2, "num_layers": 1, "dropout": 0.0,
                },
                "sources": [FEED],
                # One map for the whole feed: whatever the last group wrote.
                "source_stats": {FEED: {"mean": 1_000_000.0, "std": 40_000.0}},
            },
            path,
        )
        return path

    def test_series_grain_checkpoint_is_applied_per_series(self, panel_run, tmp_path):
        _, _, output_dir = panel_run
        import shutil

        job_id = "job-panel"
        os.makedirs(os.path.join(str(tmp_path), job_id), exist_ok=True)
        shutil.copyfile(
            os.path.join(output_dir, "best_model.pt"),
            os.path.join(str(tmp_path), job_id, "best_model.pt"),
        )
        orch = EngineOrchestrator(job_id, str(tmp_path), config={"batch_size": 8})
        model = orch._get_model()
        predictions = orch._predict(model, {"timeseries": _panel_frame()})
        assert orch.stats_grain == "series"
        assert set(predictions["stats_provenance"]) == set(SERIES_KEYS)
        assert set(predictions["stats_provenance"].values()) == {"checkpoint"}
        assert set(np.asarray(predictions["series_ids"])) == set(SERIES_KEYS)

    def test_feed_grain_checkpoint_serving_entities_says_so(self, tmp_path, caplog):
        job_id = "job-legacy"
        self._legacy_checkpoint(str(tmp_path), job_id)
        orch = EngineOrchestrator(job_id, str(tmp_path), config={"batch_size": 8})
        orch._get_model()
        assert orch.stats_grain == "feed"
        with caplog.at_level("WARNING"):
            predictions = orch._predict(orch._get_model(), {"timeseries": _panel_frame()})
        assert set(predictions["stats_provenance"].values()) == {"checkpoint_feed_grain"}
        assert any(
            "feed-grain" in record.message.lower() for record in caplog.records
        ), "the mismatch between feed statistics and entity windows must be reported"

    def test_feed_grained_payload_keeps_the_existing_provenance(self, tmp_path):
        job_id = "job-feed"
        self._legacy_checkpoint(str(tmp_path), job_id)
        orch = EngineOrchestrator(job_id, str(tmp_path), config={"batch_size": 8})
        # The legacy manifest above declares one source; score a feed-grain
        # payload for that same source so the grains agree.
        frame = _panel_frame().drop(columns=["series_id", "entity_id"])
        orch._get_model()
        predictions = orch._predict(orch._get_model(), {"timeseries": frame})
        assert predictions["stats_provenance"] == {FEED: "checkpoint"}


class TestPredictionPathReportsItsGrain:
    """``_prepare_sequence`` consulted by a feed label against a series-grain
    checkpoint has no entry describing a whole feed. It must normalize from the
    payload and say so, not borrow one entity's scale for the entire feed.
    ``predict_risk_series`` itself now groups by ``series_id`` (see
    ``TestPredictionSeriesGroupsBySeries``), so this is the safety net for the
    point-prediction path and any direct feed-label lookup."""

    @staticmethod
    def _engine(output_dir: str) -> RealPredictionEngine:
        return RealPredictionEngine(
            model_path=os.path.join(output_dir, "best_model.pt"),
            device=torch.device("cpu"),
            config={"sequence_length": SEQUENCE_LENGTH},
        )

    def test_checkpoint_grain_is_recorded_on_load(self, panel_run):
        _, _, output_dir = panel_run
        engine = self._engine(output_dir)
        assert engine.stats_grain == "series"
        assert set(engine.source_stats) == set(SERIES_KEYS)

    def test_feed_grain_lookup_of_series_statistics_is_reported(self, panel_run, caplog):
        """A feed label is not a series label: the lookup misses, the window is
        standardized from its own observations, and the reason is logged."""
        _, _, output_dir = panel_run
        engine = self._engine(output_dir)
        values = np.linspace(100.0, 112.0, 12, dtype=np.float32)
        with caplog.at_level("WARNING"):
            _, stats = engine._prepare_sequence(values, FEED)
        assert any(
            "series-grain" in record.message.lower() for record in caplog.records
        ), "a series-grain checkpoint applied per feed must announce the mismatch"
        assert stats["mean"] == pytest.approx(float(values.mean()), rel=1e-4)
        # Not either entity's level: borrowing one of them is the defect.
        for entity in ENTITIES:
            assert abs(stats["mean"] - LEVELS[entity]) > 1.0

    def test_feed_grain_checkpoint_still_serves_a_feed_grain_lookup(self, tmp_path):
        """Pre-fix manifests are not invalidated by this change: a feed-keyed map
        with no ``stats_grain`` keeps its existing behaviour, quietly, because
        the grains agree."""
        torch.manual_seed(9)
        model = MultiScaleTemporalAttentionModel(
            num_sources=1,
            sequence_length=SEQUENCE_LENGTH,
            d_model=8,
            nhead=2,
            num_layers=1,
            dropout=0.0,
        )
        path = str(tmp_path / "best_model.pt")
        safe_torch_save(
            {
                "model_state_dict": model.state_dict(),
                "config": {
                    "model": "temporal_attention",
                    "sequence_length": SEQUENCE_LENGTH,
                    "d_model": 8, "nhead": 2, "num_layers": 1, "dropout": 0.0,
                },
                "sources": [FEED],
                "source_stats": {FEED: {"mean": 1_000_000.0, "std": 40_000.0}},
            },
            path,
        )
        engine = RealPredictionEngine(
            model_path=path,
            device=torch.device("cpu"),
            config={"sequence_length": SEQUENCE_LENGTH},
        )
        assert engine.stats_grain == "feed"
        values = np.full(12, 999_950.0, dtype=np.float32)
        _, stats = engine._prepare_sequence(values, FEED)
        assert stats["mean"] == pytest.approx(1_000_000.0)


class TestPredictionSeriesGroupsBySeries:
    """``predict_risk_series`` must score a panel feed per entity, not as one
    interleaved series. L-42 fixed the statistics grain on the training path and
    the orchestrator's scoring loop; this is the per-timestep risk-series path,
    which grouped ``working`` by ``source_code`` and collapsed every entity of a
    feed into a single fabricated series until this fix."""

    def test_panel_is_scored_per_series(self, panel_run):
        from backend.modules.data.quality_gate import QualityAttestation

        _, _, output_dir = panel_run
        attestation = QualityAttestation(
            job_id="job-panel-series",
            verified=True,
            checked_at="2024-01-01T00:00:00+00:00",
        )
        engine = RealPredictionEngine(
            model_path=os.path.join(output_dir, "best_model.pt"),
            device=torch.device("cpu"),
            config={"sequence_length": SEQUENCE_LENGTH},
            quality_attestation=attestation,
        )
        result = engine.predict_risk_series(_panel_frame(), attestation=attestation)

        # One feed, two entities: the series grain, not the feed grain.
        assert result.n_sources == 1
        assert result.sources == [FEED]
        assert result.n_series == 2
        assert sorted(result.series_ids) == sorted(SERIES_KEYS)

        # Each entity keeps its own contiguous window; the single seam sits
        # between the two series, not between interleaved rows.
        per_series = ROWS - SEQUENCE_LENGTH + 1
        assert result.n_steps == 2 * per_series
        assert result.boundaries == [per_series]
        assert set(result.frame["series"].unique()) == set(SERIES_KEYS)
        assert set(result.frame["source"].unique()) == {FEED}

        # The frame is grouped, never interleaved: each entity's rows form one
        # contiguous run.
        for key in SERIES_KEYS:
            positions = np.flatnonzero(
                result.frame["series"].to_numpy() == key
            )
            assert positions.size == per_series, f"expected {per_series} rows for {key}"
            assert (np.diff(positions) == 1).all(), f"{key} rows are interleaved"

        # A series-grain checkpoint carries each entity's own statistics, so
        # nothing falls back to the payload window: no grain mismatch.
        assert set(result.stats_provenance) == set(SERIES_KEYS)
        assert set(result.stats_provenance.values()) == {"checkpoint"}
