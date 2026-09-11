"""Risk analysis constants and thresholds.

The constants that supported the removed heuristic scoring were deleted rather
than left in place. They were:

* ``VULNERABILITY_NORMALIZATION_FACTOR = 1e9`` -- converted dollars into "risk
  units" so a score would land in ``[0, 1]``. The failure thresholds were then
  calibrated against that arbitrary scale, which made them meaningless: change
  the unit of account and every institution's score moves while nothing about the
  world does.
* ``VOLATILITY_NORMALIZATION_FACTOR`` / ``TREND_NORMALIZATION_FACTOR`` -- same
  problem, and combined as ``overall * 0.7 + volatility * 0.2 + trend * 0.1`` to
  produce a "market liquidity risk" channel from a single prediction.
* ``OPERATIONAL_RISK_*`` -- bounds on a number derived from a coefficient of
  variation, then clipped into a range chosen by hand.
* ``WEIGHT_MARKET_LIQUIDITY`` / ``WEIGHT_FUNDING_LIQUIDITY`` /
  ``WEIGHT_SYSTEMIC_RISK`` / ``WEIGHT_OPERATIONAL_RISK`` -- the 0.35/0.35/0.25/
  0.05 blend applied to three scalar multiples of one array.
* ``WEIGHT_INDIVIDUAL_RISK`` / ``WEIGHT_SYSTEMIC_CONCENTRATION`` /
  ``WEIGHT_NETWORK_INTERCONNECTEDNESS`` -- a systemic-risk blend whose inputs
  were a risk score, an exposure rescaled by ``1e10``, and a connection count
  rescaled by ``20``.
* ``SIGNIFICANT_CONTRIBUTION_THRESHOLD`` / ``CONFIDENCE_WIDTH_*`` -- cut-offs
  applied to the removed gradient*attention attributions.
* ``CORRELATION_THRESHOLD`` / ``SIGNIFICANT_CONNECTIONS_THRESHOLD`` -- used by
  the removed static-graph builder, which thresholded pairwise correlation and
  treated the result as an exposure network.
* ``RECENT_DATA_WINDOW`` / ``MARKET_VOLATILITY_HIGH_THRESHOLD`` -- windows and
  cut-offs used only by the removed heuristic channels.

Thresholds below are kept because something still consumes them, or because they
are ordinary model defaults rather than calibrated score cut-offs.
"""

# Risk level thresholds (0-1 scale)
RISK_THRESHOLD_LOW = 0.3
RISK_THRESHOLD_MODERATE = 0.6
RISK_THRESHOLD_HIGH = 0.85

# Risk level thresholds (0-100 scale)
#
# Derived from the 0-1 scale above rather than written out a second time. They
# previously read 30/60/80, so the two scales disagreed at the top band: 0.82 was
# "high" on the 0-1 scale and "critical" on the 0-100 scale. The decimal literals
# had drifted from the source of truth they were meant to mirror, which is the
# failure a second copy invites. Deriving them makes the disagreement
# unrepresentable.
RISK_THRESHOLD_LOW_PERCENT = int(round(RISK_THRESHOLD_LOW * 100))
RISK_THRESHOLD_MODERATE_PERCENT = int(round(RISK_THRESHOLD_MODERATE * 100))
RISK_THRESHOLD_HIGH_PERCENT = int(round(RISK_THRESHOLD_HIGH * 100))

# Systemic risk thresholds
SYSTEMIC_RISK_THRESHOLD_MODERATE = 60
SYSTEMIC_RISK_THRESHOLD_HIGH = 80

# High risk thresholds for network analysis
HIGH_RISK_THRESHOLD = 0.7
CRITICAL_RISK_THRESHOLD = 0.9

# Data quality thresholds
MISSING_DATA_THRESHOLD = 0.3
DATA_QUALITY_THRESHOLD_GOOD = 60.0

# Model performance thresholds
R2_EXCELLENT_THRESHOLD = 0.95
R2_GOOD_THRESHOLD = 0.8
R2_PRODUCTION_THRESHOLD = 0.9
R2_TESTING_THRESHOLD = 0.7

# Memory thresholds (GB)
MEMORY_MINIMUM_GB = 16
MEMORY_RECOMMENDED_GB = 32
GPU_MEMORY_MINIMUM_GB = 8
GPU_MEMORY_RECOMMENDED_GB = 24

# Temporal analysis window sizes
TEMPORAL_WINDOW_SHORT = 7
TEMPORAL_WINDOW_MEDIUM = 14

# Data quality weights
WEIGHT_DATA_COMPLETENESS = 0.6
WEIGHT_DATA_CONSISTENCY = 0.4

# Data analysis weights
WEIGHT_VALIDATION_RESULTS = 0.4
WEIGHT_DATA_COMPLETENESS_ANALYSIS = 0.3
WEIGHT_CLEANING_SUCCESS = 0.3

# Orchestrator thresholds
DATA_QUALITY_THRESHOLD = 70.0
DATA_COMPLETENESS_MINIMUM = 80.0

# Sequence lengths
DEFAULT_SEQUENCE_LENGTH = 30

# Model defaults
DEFAULT_HIDDEN_DIM = 128
DEFAULT_NUM_HEADS = 8
DEFAULT_NUM_LAYERS = 3
