"""Composition tests for the training path.

The unit suite verifies components; nothing in it ever composed
``MultiScaleTrainer.train`` or ``ModelTrainer.train`` end to end, which is how
three production defects survived a green suite (fourth-round quant review,
findings F1, F2, F3, F5, F8):

* ``ReduceLROnPlateau(verbose=True)`` raises ``TypeError`` under the pinned
  torch 2.14 -- no training job could run at all.
* An empty validation split made ``_validate`` report ``0.0`` forever, which
  froze model selection at the epoch-0 checkpoint while the job "completed
  successfully".
* Val/test datasets standardized themselves, so reported metrics were computed
  in a space the deployed model never inhabited.
* The production split was a positional ``iloc`` cut across a source-major
  frame -- a split by SOURCE, not by time, which is also what emptied
  validation in the first place.

These tests compose the trainers the way ``run_training`` does, on frames
shaped the way the collector produces them. Synthetic values are fine here:
this file tests the machinery, never a risk claim. Skipped when torch is
absent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from backend.modules.engine.multi_scale_trainer import (  # noqa: E402
    MultiScaleTemporalAttentionModel,
    MultiScaleTrainer,
    MultiSourceDataset,
    is_degenerate_standardization,
)
from backend.modules.engine.trainer import (  # noqa: E402
    ModelTrainer,
    TimeSeriesDataset,
    default_training_windows,
    split_train_val_by_date,
)

SOURCES = ("SRC_A", "SRC_B", "SRC_C")
ROWS_PER_SOURCE = 40
SEQUENCE_LENGTH = 5


def _multi_source_frame(rows: int = ROWS_PER_SOURCE, sources=SOURCES) -> pd.DataFrame:
    """A source-major long frame, exactly like the formatter concatenates."""
    rng = np.random.default_rng(11)
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    frames = []
    for index, source in enumerate(sources):
        values = 10.0 * (index + 1) + rng.normal(0.0, 1.0, rows).cumsum()
        frames.append(
            pd.DataFrame({
                "Date": dates,
                "date": dates,
                "Close": values,
                "Value": values,
                "source_code": source,
            })
        )
    return pd.concat(frames, ignore_index=True)


def _split_by_date(df: pd.DataFrame, train_frac: float = 0.7, val_frac: float = 0.15):
    dates = df["Date"]
    dmin, dmax = dates.min(), dates.max()
    t1 = dmin + (dmax - dmin) * train_frac
    t2 = dmin + (dmax - dmin) * (train_frac + val_frac)
    train_df = df[dates <= t1]
    val_df = df[(dates > t1) & (dates <= t2)]
    test_df = df[dates > t2]
    return train_df, val_df, test_df


class TestTrainersActuallyRun:
    """F1: the training loop must execute under the pinned torch."""

    def test_multi_scale_trainer_completes_a_training_run(self, tmp_path):
        train_df, val_df, test_df = _split_by_date(_multi_source_frame())
        trainer = MultiScaleTrainer(
            model_type="temporal_attention",
            device=torch.device("cpu"),
            config={
                "epochs": 2,
                "sequence_length": SEQUENCE_LENGTH,
                "batch_size": 8,
                "d_model": 8,
                "nhead": 2,
                "num_layers": 1,
                "dropout": 0.0,
            },
        )
        metrics = trainer.train(train_df, val_df, test_df, str(tmp_path))
        assert metrics.total_epochs == 2
        assert np.isfinite(metrics.test_loss)
        assert (tmp_path / "best_model.pt").exists()

    def test_single_scale_trainer_completes_a_training_run(self, tmp_path):
        rng = np.random.default_rng(3)
        n = 90
        df = pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "Value": rng.normal(0.0, 1.0, n).cumsum(),
            "Feature1": rng.normal(0.0, 1.0, n),
        })
        train_df, val_df, test_df = df.iloc[:60], df.iloc[60:75], df.iloc[75:]
        trainer = ModelTrainer(
            model_type="temporal_attention",
            device=torch.device("cpu"),
            config={
                "epochs": 2,
                "sequence_length": SEQUENCE_LENGTH,
                "batch_size": 8,
                "d_model": 8,
                "nhead": 2,
                "num_layers": 1,
                "dropout": 0.0,
            },
        )
        metrics = trainer.train(train_df, val_df, test_df, str(tmp_path))
        assert metrics.total_epochs == 2
        assert np.isfinite(metrics.test_loss)


class TestEmptySplitsFailLoudly:
    """F2: an empty validation split must abort, never select epoch 0."""

    def test_multi_scale_rejects_empty_validation(self, tmp_path):
        # The historical production defect: a positional iloc split of a
        # source-major frame puts whole sources on the validation side, whose
        # IDs are not in the training source map, so the dataset skips them.
        df = _multi_source_frame()
        train_df = df[df["source_code"].isin(("SRC_A", "SRC_B"))]
        val_df = df[df["source_code"] == "SRC_C"]
        test_df = df[df["source_code"].isin(("SRC_A", "SRC_B"))].tail(20)
        trainer = MultiScaleTrainer(
            model_type="temporal_attention",
            device=torch.device("cpu"),
            config={"epochs": 1, "sequence_length": SEQUENCE_LENGTH,
                    "d_model": 8, "nhead": 2, "num_layers": 1},
        )
        with pytest.raises(ValueError, match="[Vv]alidation dataset is empty"):
            trainer.train(train_df, val_df, test_df, str(tmp_path))

    def test_multi_scale_rejects_empty_test(self, tmp_path):
        df = _multi_source_frame()
        train_df, val_df, _ = _split_by_date(df)
        empty_test = df.iloc[0:0]
        trainer = MultiScaleTrainer(
            model_type="temporal_attention",
            device=torch.device("cpu"),
            config={"epochs": 1, "sequence_length": SEQUENCE_LENGTH,
                    "d_model": 8, "nhead": 2, "num_layers": 1},
        )
        with pytest.raises(ValueError, match="[Tt]est dataset is empty"):
            trainer.train(train_df, val_df, empty_test, str(tmp_path))

    def test_single_scale_rejects_empty_validation(self, tmp_path):
        rng = np.random.default_rng(5)
        n = 60
        df = pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "Value": rng.normal(0.0, 1.0, n).cumsum(),
        })
        trainer = ModelTrainer(
            model_type="temporal_attention",
            device=torch.device("cpu"),
            config={"epochs": 1, "sequence_length": SEQUENCE_LENGTH,
                    "d_model": 8, "nhead": 2, "num_layers": 1},
        )
        with pytest.raises(ValueError, match="[Vv]alidation dataset is empty"):
            trainer.train(df, df.iloc[0:0], df.tail(20), str(tmp_path))


class TestNormalizationStatsComeFromTheTrainSplit:
    """F3: one standardized space -- the training split's -- for every split."""

    def test_multi_source_dataset_uses_provided_stats(self):
        df = _multi_source_frame()
        train_df, val_df, _ = _split_by_date(df)
        train_ds = MultiSourceDataset(train_df, sequence_length=SEQUENCE_LENGTH)
        val_ds = MultiSourceDataset(
            val_df,
            sequence_length=SEQUENCE_LENGTH,
            source_to_id=train_ds.source_to_id,
            source_stats=train_ds.source_stats,
        )
        assert val_ds.source_stats == train_ds.source_stats

        # The stored sequences must be standardized with the TRAIN stats: for
        # a known source, recompute the expected normalization by hand.
        source = "SRC_A"
        stats = train_ds.source_stats[source]
        rows = val_df[val_df["source_code"] == source].sort_values("Date")
        raw = pd.to_numeric(rows["Close"], errors="coerce").to_numpy(float)
        expected_last = (raw[-1] - stats["mean"]) / stats["std"]
        # The final target of the final window is the last row's normalized value.
        val_targets_for_source = [
            t for t, sid in zip(val_ds.targets, val_ds.source_ids)
            if sid == train_ds.source_to_id[source]
        ]
        assert val_targets_for_source[-1] == pytest.approx(expected_last, rel=1e-5)

    def test_multi_source_dataset_skips_sources_without_train_stats(self):
        df = _multi_source_frame()
        train_df = df[df["source_code"] != "SRC_C"]
        unseen_df = df[df["source_code"] == "SRC_C"]
        train_ds = MultiSourceDataset(train_df, sequence_length=SEQUENCE_LENGTH)
        unseen_ds = MultiSourceDataset(
            unseen_df,
            sequence_length=SEQUENCE_LENGTH,
            source_to_id=train_ds.source_to_id,
            source_stats=train_ds.source_stats,
        )
        assert len(unseen_ds) == 0

    def test_panel_series_do_not_share_temporal_windows(self):
        dates = pd.date_range("2024-01-01", periods=40, freq="D")
        frame = pd.concat(
            [
                pd.DataFrame({
                    "Date": dates,
                    "Close": np.arange(40, dtype=float),
                    "Value": np.arange(40, dtype=float),
                    "source_code": "PANEL",
                    "series_id": "PANEL::A::B",
                }),
                pd.DataFrame({
                    "Date": dates,
                    "Close": 100.0 + np.arange(40, dtype=float),
                    "Value": 100.0 + np.arange(40, dtype=float),
                    "source_code": "PANEL",
                    "series_id": "PANEL::B::A",
                }),
            ],
            ignore_index=True,
        )

        dataset = MultiSourceDataset(frame, sequence_length=SEQUENCE_LENGTH)

        # Each 40-row entity contributes 40 - window observations. A source-
        # grouped implementation would incorrectly produce one extra window
        # per seam and a sequence containing the end of A followed by B.
        assert len(dataset) == 2 * (40 - SEQUENCE_LENGTH)
        assert set(dataset.source_ids.tolist()) == {dataset.source_to_id["PANEL"]}
        assert dataset.sources.tolist() == ["PANEL"]

    def test_time_series_dataset_uses_provided_stats(self):
        rng = np.random.default_rng(9)
        n = 80
        df = pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "Value": rng.normal(5.0, 2.0, n).cumsum(),
        })
        train_ds = TimeSeriesDataset(df.iloc[:60], sequence_length=SEQUENCE_LENGTH)
        test_ds = TimeSeriesDataset(
            df.iloc[60:], sequence_length=SEQUENCE_LENGTH,
            norm_stats=train_ds.normalization_stats(),
        )
        assert test_ds.target_mean == pytest.approx(train_ds.target_mean)
        assert test_ds.target_std == pytest.approx(train_ds.target_std)
        # The evaluation frame's own stats would differ; the passed stats won.
        own = TimeSeriesDataset(df.iloc[60:], sequence_length=SEQUENCE_LENGTH)
        assert own.target_mean != pytest.approx(train_ds.target_mean, rel=1e-3)

    def test_time_series_dataset_rejects_missing_feature_columns(self):
        rng = np.random.default_rng(2)
        n = 40
        df = pd.DataFrame({
            "Value": rng.normal(0, 1, n),
            "Feature1": rng.normal(0, 1, n),
        })
        train_ds = TimeSeriesDataset(df, sequence_length=SEQUENCE_LENGTH)
        stats = train_ds.normalization_stats()
        with pytest.raises(ValueError, match="missing training feature columns"):
            TimeSeriesDataset(df[["Value"]], sequence_length=SEQUENCE_LENGTH,
                              norm_stats=stats)


class TestPaddingMatchesInference:
    """F8: short windows zero-pad at the standardized mean, like the engine."""

    def test_short_source_windows_are_zero_padded_not_edge_padded(self):
        rows = 8  # fewer than 2 * SEQUENCE_LENGTH, forcing window shrink + pad
        dates = pd.date_range("2024-01-01", periods=rows, freq="D")
        values = np.arange(1.0, rows + 1.0) * 100.0
        df = pd.DataFrame({
            "Date": dates, "Close": values, "Value": values,
            "source_code": "SRC_SHORT",
        })
        ds = MultiSourceDataset(df, sequence_length=SEQUENCE_LENGTH)
        assert len(ds) > 0
        window = ds.sequences[0]
        assert window.shape[0] == SEQUENCE_LENGTH
        # The shrinkable window is len-1 = 7 -> wait: window = min(5, 7) = 5,
        # no padding needed. Use a source too short for a full window instead.
        short_df = pd.DataFrame({
            "Date": dates[:4], "Close": values[:4], "Value": values[:4],
            "source_code": "SRC_SHORT",
        })
        short_ds = MultiSourceDataset(short_df, sequence_length=SEQUENCE_LENGTH)
        assert len(short_ds) > 0
        padded = short_ds.sequences[0]
        pad_width = SEQUENCE_LENGTH - (len(short_df) - 1)
        assert pad_width > 0
        # Constant zero padding (standardized mean), NOT a copy of the first
        # observation the way mode='edge' produced.
        assert np.all(padded[:pad_width] == 0.0)
        first_observed = (values[:4] - short_ds.source_stats["SRC_SHORT"]["mean"]) / \
            short_ds.source_stats["SRC_SHORT"]["std"]
        assert padded[pad_width] == pytest.approx(first_observed[0])


class TestChronologicalSplits:
    """F5: splits are cuts in time, not positional cuts across sources."""

    def test_default_windows_span_the_payload(self):
        dmin = pd.Timestamp("2021-01-01")
        dmax = pd.Timestamp("2026-01-01")
        start, train_end, end = default_training_windows(dmin, dmax, train_fraction=0.8)
        assert start == dmin
        assert end == dmax
        assert train_end == dmin + (dmax - dmin) * 0.8
        assert start < train_end < end

    def test_default_windows_reject_degenerate_ranges(self):
        with pytest.raises(ValueError):
            default_training_windows(pd.Timestamp("2024-01-01"),
                                     pd.Timestamp("2024-01-01"))

    def test_val_split_is_chronological_and_keeps_every_source(self):
        df = _multi_source_frame()
        train_part, val_part, cutoff = split_train_val_by_date(df, "Date", val_fraction=0.2)

        # Every validation date is strictly after every training date...
        assert pd.to_datetime(train_part["Date"]).max() <= cutoff
        assert pd.to_datetime(val_part["Date"]).min() > cutoff
        # ...and every source keeps temporal continuity on both sides: the
        # positional cut this replaces put whole SOURCES on the val side.
        assert set(train_part["source_code"]) == set(SOURCES)
        assert set(val_part["source_code"]) == set(SOURCES)

    def test_val_split_rejects_a_single_timestamp_span(self):
        df = pd.DataFrame({
            "Date": [pd.Timestamp("2024-01-01")] * 5,
            "Value": np.arange(5.0),
        })
        with pytest.raises(ValueError, match="single timestamp"):
            split_train_val_by_date(df, "Date")

    def test_positional_split_would_have_leaked_sources_regression(self):
        """The defect this replaces, asserted directly: on a source-major
        frame, an iloc 80/20 cut assigns whole sources to validation."""
        five = ("SRC_A", "SRC_B", "SRC_C", "SRC_D", "SRC_E")
        df = _multi_source_frame(sources=five)
        cut = int(len(df) * 0.8)
        old_train, old_val = df.iloc[:cut], df.iloc[cut:]
        old_train_sources = set(old_train["source_code"])
        old_val_sources = set(old_val["source_code"])
        # The trailing source sits entirely in the positional val side: the
        # multi-scale dataset would skip it (unseen source id), emptying
        # validation and freezing model selection at epoch 0.
        stranded = old_val_sources - old_train_sources
        assert stranded, "expected the positional split to strand at least one source"
        train_part, val_part, _ = split_train_val_by_date(df, "Date", val_fraction=0.2)
        assert set(val_part["source_code"]) <= set(train_part["source_code"])
        assert set(val_part["source_code"]) == set(five)


class TestDegenerateStandardization:
    """A near-constant series (relative std below the floor) must be skipped,
    not standardized. The 6.1.0 full-panel retrain hit this: an AI4RISK edge
    that was constant 2200 in the training split (std 0 -> floor 1e-8) and
    moved by ~310 afterwards produced z ~ 3e10, a squared error of 1e21 from
    a handful of samples that dominated the entire validation loss (4e18)
    and made model selection meaningless."""

    def test_is_degenerate_classifies_floor_std_against_scale(self):
        # Constant series: std 0.
        assert is_degenerate_standardization(2200.0, 0.0)
        assert is_degenerate_standardization(1.0, 1e-8)
        # Near-constant against a large scale: 1e-8 << 1e-6 * 2200.
        assert is_degenerate_standardization(2200.0, 1e-8)
        # Non-finite std.
        assert is_degenerate_standardization(5.0, float("nan"))
        # A genuine small scale near zero: 0.5 against scale 1.0 is fine.
        assert not is_degenerate_standardization(0.0, 0.5)
        # Tiny scale near zero: 1e-8 << 1e-6 * 1.0.
        assert is_degenerate_standardization(0.0, 1e-8)
        # A real relative spread: 1.0 against 1000 is 1e-3 > 1e-6.
        assert not is_degenerate_standardization(1000.0, 1.0)

    def _two_series_train_frame(self):
        """One healthy random-walk series and one near-constant series, shaped
        like the collector's source-major frame."""
        dates = pd.date_range("2024-01-01", periods=40, freq="D")
        rng = np.random.default_rng(7)
        healthy = 10.0 + rng.normal(0.0, 1.0, 40).cumsum()
        flat = np.full(40, 2200.0)
        return pd.DataFrame({
            "Date": list(dates) + list(dates),
            "date": list(dates) + list(dates),
            "Close": list(healthy) + list(flat),
            "Value": list(healthy) + list(flat),
            "source_code": ["SRC_HEALTHY"] * 40 + ["SRC_FLAT"] * 40,
        })

    def test_train_dataset_skips_the_near_constant_series(self):
        df = self._two_series_train_frame()
        dataset = MultiSourceDataset(df, sequence_length=SEQUENCE_LENGTH)
        # The healthy series trained; the flat one was refused, not standardized.
        assert "SRC_HEALTHY" in dataset.series_labels
        assert "SRC_FLAT" not in dataset.series_labels
        assert "SRC_FLAT" not in dataset.source_stats
        # No standardized value anywhere near the floor-driven magnitude.
        assert np.abs(dataset.targets).max() < 1e3
        assert np.abs(dataset.sequences).max() < 1e3

    def test_external_split_refuses_degenerate_train_stats(self):
        df = self._two_series_train_frame()
        train = df[df["source_code"] == "SRC_HEALTHY"]
        # Hand the external path a degenerate stat set for a flat series and
        # check it is skipped rather than standardized at a 1e-8 floor.
        flat_frame = df[df["source_code"] == "SRC_FLAT"].copy()
        dataset = MultiSourceDataset(
            flat_frame,
            sequence_length=SEQUENCE_LENGTH,
            source_stats={"SRC_FLAT": {"mean": 2200.0, "std": 1e-8}},
        )
        assert len(dataset) == 0

    def test_tiny_real_std_step_change_is_clipped_not_blown_up(self):
        """The second half of the 6.1.0 blowup: a series with a tiny but real
        std in the training split (an AI4RISK edge drifting 1.6e-5 around 0.27
        -- above the degenerate floor, so it trains) that steps by 1.3 in the
        evaluation split. The step's z is ~8e4, a squared error of 6.6e9 that
        would still dominate the MSE objective. It must be clipped instead."""
        train_dates = pd.date_range("2024-01-01", periods=30, freq="D")
        rng = np.random.default_rng(21)
        train = 0.27 + rng.normal(0.0, 1.6e-5, 30)
        train_df = pd.DataFrame({
            "Date": train_dates, "date": train_dates,
            "Value": train, "source_code": ["SRC_TINY"] * len(train_dates),
        })
        train_dataset = MultiSourceDataset(train_df, sequence_length=SEQUENCE_LENGTH)
        # Above the degenerate floor: it trains and publishes stats.
        assert "SRC_TINY" in train_dataset.series_labels
        std = train_dataset.source_stats["SRC_TINY"]["std"]
        assert std > 1e-6

        eval_dates = pd.date_range("2024-02-01", periods=SEQUENCE_LENGTH + 2, freq="D")
        eval_values = np.array([0.27] * (SEQUENCE_LENGTH + 1) + [0.27 + 1.3])
        eval_df = pd.DataFrame({
            "Date": eval_dates, "date": eval_dates,
            "Value": eval_values, "source_code": ["SRC_TINY"] * len(eval_dates),
        })
        eval_dataset = MultiSourceDataset(
            eval_df,
            sequence_length=SEQUENCE_LENGTH,
            source_to_id=train_dataset.source_to_id,
            source_stats=train_dataset.source_stats,
        )
        assert len(eval_dataset) > 0
        # Without the clip the step's z is ~1.3/std = 8e4; it must be bounded.
        unclipped = (eval_values[-1] - train_dataset.source_stats["SRC_TINY"]["mean"]) / std
        assert unclipped > 1000, "fixture no longer reproduces the blowup"
        assert np.abs(eval_dataset.sequences).max() <= 10.0 + 1e-6
        assert np.abs(eval_dataset.targets).max() <= 10.0 + 1e-6


class TestBaselineComparison:
    """The walk-forward baseline comparison must actually measure a source
    that has enough windows, instead of skipping everything.

    Two latent defects hid in this path and were only reachable once a series
    survived the window-count guard:
    1. sliding_window_view yields n - seq_len + 1 windows while targets_raw
       has n - seq_len entries, so the size guard fired for EVERY long series
       and every source was skipped ("not enough windows"), leaving
       mean_lift null.
    2. the frozen-model adapter reshaped features to (batch, seq_len, 1) but
       the model's forward takes (batch, seq_len); the resulting RuntimeError
       is not caught by the (TypeError, ValueError) guard and would have
       crashed the training job.
    """

    SEQ = 30
    N_TRAIN = 200
    N_TEST = 100  # -> 70 windows after the off-by-one drop; 61 would be <30? no: 100-30=70 >= 30

    def _trainer_with_test_dataset(self):
        dates = pd.date_range("2024-01-01", periods=self.N_TRAIN + self.N_TEST, freq="D")
        rng = np.random.default_rng(7)
        values = 100.0 + rng.normal(0.0, 1.0, self.N_TRAIN + self.N_TEST).cumsum()
        frame = pd.DataFrame({
            "Date": dates, "date": dates, "Value": values,
            "source_code": "SRC_RATES",
        })
        train_df = frame.iloc[: self.N_TRAIN].reset_index(drop=True)
        test_df = frame.iloc[self.N_TRAIN :].reset_index(drop=True)
        train_dataset = MultiSourceDataset(train_df, sequence_length=self.SEQ)
        test_dataset = MultiSourceDataset(
            test_df,
            sequence_length=self.SEQ,
            source_to_id=train_dataset.source_to_id,
            source_stats=train_dataset.source_stats,
        )
        trainer = MultiScaleTrainer(
            model_type="temporal_attention",
            device=torch.device("cpu"),
            config={
                "sequence_length": self.SEQ,
                "d_model": 16,
                "nhead": 2,
                "num_layers": 1,
                "dropout": 0.1,
            },
        )
        trainer.model = MultiScaleTemporalAttentionModel(
            num_sources=len(train_dataset.sources),
            sequence_length=self.SEQ,
            d_model=16,
            nhead=2,
            num_layers=1,
            dropout=0.1,
        )
        return trainer, test_dataset

    def test_long_series_is_measured_not_skipped(self):
        trainer, test_dataset = self._trainer_with_test_dataset()
        result = trainer._baseline_comparison(test_dataset)
        assert result is not None
        entry = result["per_source"]["SRC_RATES"]
        assert "skipped" not in entry, (
            f"100-point series has {self.N_TEST - self.SEQ} windows and must be "
            f"measured, got: {entry}"
        )
        assert "primary_metrics" in entry and "lift" in entry

    def test_short_series_is_skipped_honestly(self):
        trainer, _ = self._trainer_with_test_dataset()
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        rng = np.random.default_rng(8)
        short = pd.DataFrame({
            "Date": dates, "date": dates,
            "Value": 50.0 + rng.normal(0.0, 1.0, 30).cumsum(),
            "source_code": "SRC_SHORT",
        })
        train_df = short.iloc[:20].reset_index(drop=True)
        test_df = short.iloc[20:].reset_index(drop=True)
        train_dataset = MultiSourceDataset(train_df, sequence_length=self.SEQ)
        test_dataset = MultiSourceDataset(
            test_df,
            sequence_length=self.SEQ,
            source_to_id=train_dataset.source_to_id,
            source_stats=train_dataset.source_stats,
        )
        # 10 test points < seq_len + 10: an honest skip, not a silent drop.
        result = trainer._baseline_comparison(test_dataset)
        entry = result["per_source"]["SRC_SHORT"]
        assert "skipped" in entry
