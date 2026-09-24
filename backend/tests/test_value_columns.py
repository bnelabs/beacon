"""Tests for the per-series value-column selection shared by the training,
prediction, and backtest paths.

The joined collection frame carries several value columns at once (``Close``
from OHLC rows, ``Value`` from indicator rows), so every reader must pick the
column that actually has data for each series. Reading the wrong column
silently produces an all-NaN series, which the model then scores as a
degenerate constant (finding F9).
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.modules.engine.value_columns import (
    VALUE_COLUMN_CANDIDATES,
    select_value_column,
)


def test_candidates_covers_both_shapes():
    assert "Close" in VALUE_COLUMN_CANDIDATES
    assert "Value" in VALUE_COLUMN_CANDIDATES
    assert "close" in VALUE_COLUMN_CANDIDATES
    assert "value" in VALUE_COLUMN_CANDIDATES


def test_close_frame_picks_close():
    frame = pd.DataFrame({"Close": [1.0, 2.0], "Value": [None, None]})
    assert select_value_column(frame) == "Close"


def test_value_frame_picks_value():
    frame = pd.DataFrame({"Value": [1.0, 2.0]})
    assert select_value_column(frame) == "Value"


def test_prefers_column_with_data_over_schema_presence():
    # Both columns exist; only Value has data. The previous frame-wide
    # rule picked Close (present in the schema) and read all NaN.
    frame = pd.DataFrame({"Close": [None, None], "Value": [1.0, 2.0]})
    assert select_value_column(frame) == "Value"


def test_partial_nan_still_counts_as_data():
    frame = pd.DataFrame({"Close": [None, 2.0, None], "Value": [1.0, None, 3.0]})
    # Close is checked first among candidates and has at least one value.
    assert select_value_column(frame) == "Close"


def test_falls_back_when_first_column_is_all_nan():
    frame = pd.DataFrame({"Close": [None, None], "Value": [None, 1.0]})
    # Close has no data; Value does.
    assert select_value_column(frame) == "Value"


def test_all_nan_returns_none():
    empty = pd.DataFrame({"Close": [None, None], "Value": [None, None]})
    assert select_value_column(empty) is None


def test_missing_value_columns_returns_none():
    frame = pd.DataFrame({"Open": [1.0], "High": [2.0]})
    assert select_value_column(frame) is None


def test_non_numeric_values_are_coerced_to_nan():
    frame = pd.DataFrame({"Value": ["not-a-number", None]})
    assert select_value_column(frame) is None
