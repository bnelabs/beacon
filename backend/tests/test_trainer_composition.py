"""Composition tests for the training path.

The unit suite verifies components; nothing in it ever composed
``MultiScaleTrainer.train`` or ``ModelTrainer.train`` end to end, which is how
three production defects survived a green suite (docs/QUANT_REVIEW_2026-09.md,
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
    MultiScaleTrainer,
    MultiSourceDataset,
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
