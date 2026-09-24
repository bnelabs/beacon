"""Value-column selection for joined panel frames.

BEACON's collection package is a joined panel: one frame carries both OHLC
series (``Open``/``High``/``Low``/``Close``/``Volume``, mirrored lowercase)
and value series (``Value``/``value``), with every column present on every
row and NaN where a series did not populate it.

The defect this module guards against: a frame-wide membership test such as
``'Close' if 'Close' in frame.columns else 'Value'`` is always true on a
joined panel, so every value-only series reads an all-NaN column. In the
trainer that dropped the series as "no observed values" (60 of 71 sources
never entered training); in the prediction and backtest paths it fed
degenerate all-zero input, so the reported scores for those series were
garbage that looked like a signal. Select on the values, not the schema.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

#: Candidate value columns in production-filler priority order: OHLC series
#: populate ``Close`` (the lowercase ``close`` mirrors it), value series
#: populate ``Value``/``value``.
VALUE_COLUMN_CANDIDATES = ('Close', 'close', 'Value', 'value')


def select_value_column(frame: pd.DataFrame) -> Optional[str]:
    """Return the first candidate column that actually holds values here.

    Checks the data, not the schema: on a joined panel a column can exist
    (because another series filled it) while this frame's rows are all NaN
    in it. Returns ``None`` when no candidate has a single non-null value,
    in which case the caller must skip the frame (or refuse the payload)
    rather than standardise all-NaN input.
    """
    for candidate in VALUE_COLUMN_CANDIDATES:
        if candidate in frame.columns:
            if pd.to_numeric(frame[candidate], errors='coerce').notna().any():
                return candidate
    return None
