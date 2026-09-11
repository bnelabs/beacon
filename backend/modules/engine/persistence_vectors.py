"""Full-topology vectorisation of the liquidity network's persistence.

Why this module exists
----------------------

``persistent_homology.py`` reduces a network's shape to a handful of integers --
``beta_0`` and ``beta_1`` at a reference threshold, plus the merge levels. That
is enough to say *whether* the network has fragmented or lost redundancy, but it
throws away the *scale* at which each feature lives: two networks that both own
exactly one cycle are indistinguishable even when one cycle is held together by
the strongest relations in the book and the other hangs on a single
barely-there link. A model cannot learn from a difference the summary never
records.

This module keeps the whole birth-death structure and turns it into a
fixed-width numeric vector a downstream model can consume: persistence
landscapes (Bubenik, 2015), persistence images (Adams et al., 2017) and the
existing summary statistics side by side. Long-lived features dominate the
vector and short-lived, near-diagonal ones contribute almost nothing, which is
the entire point -- in this data the topology that matters is the redundancy
that survives stress, not the transient wiggles.

Filtration convention -- identical to ``persistent_homology``
--------------------------------------------------------------

At threshold ``t`` the complex is the graph ``G(t)`` holding every vertex and
every edge whose weight is ``>= t``. ``_as_adjacency`` and ``_edges`` are reused
directly, so presence (weight ``> 0``) and strength (weight ``>= t``) are tested
exactly as they are there; a zero entry is an absent relation, not a weak one.

Persistence is normally stated with ``birth <= death``, so this module stores
diagrams in the reflected **ascending** coordinate

    ``s = W_max - t``

where ``W_max`` is the largest edge weight. ``s = 0`` is the top of the
filtration (only the strongest edges are present), ``s = W_max`` is the bottom
(every positive-weight edge is present); a threshold ``t`` maps to
``s = W_max - t``. This is the superlevel-set filtration of the edge weights --
which is what the threshold semantics of ``persistent_homology`` describe --
written in ascending order. It is a reparameterisation of that one filtration,
not a second definition of it.

* **H0.** Every vertex exists at every ``t``, so all ``n`` components are born
  at ``s = 0``. A component dies at ``s = W_max - m`` when it merges at weight
  ``m``. The merge values ``m`` are taken from
  ``persistent_homology.merge_levels``, not recomputed: this codebase has
  exactly one definition of a merge level. Components that never merge inside
  the domain are essential and are *not* emitted as diagram points; their count
  is reported separately on :class:`GraphDiagrams`.

* **H1.** In descending-weight Kruskal order, every edge that joins two
  vertices already connected closes exactly one independent cycle. That edge's
  weight ``w`` is the weakest edge of the fundamental cycle, and the cycle is
  born at ``s = W_max - w``. No 2-simplices are added, so the cycle is
  essential: it is never filled. Its death is recorded as the ceiling
  ``s = W_max``, i.e. the restricted-persistence convention of clipping
  essential classes at the domain boundary. Its lifetime ``w`` is therefore the
  **bottleneck weight** of the cycle -- how weak the weakest link the redundancy
  depends on is allowed to be. This is a documented convention, not a
  homological death.

Limitations, stated plainly
---------------------------

* **Only H0 and H1 are computed.** There is no H2 and therefore no
  higher-dimensional void: H2 is identically zero because the complex is a
  graph.
* **The filtration is the edge-threshold filtration on the 1-skeleton; it is
  NOT the Vietoris-Rips flag complex.** A triangle does not fill in. Adding
  2-simplices would kill a triangle's H1 class at the instant it closes, giving
  it zero persistence, whereas this module's job is to score graph cycles; the
  choice is deliberate. The cost is that H1 features have no homological death
  (see the H1 paragraph above) and that ``beta_1`` here equals the graph cycle
  rank ``E - V + beta_0`` that ``persistent_homology.betti_numbers`` already
  reports.
* **Everything is parameter-dependent and there is no data-driven selector.**
  The landscape grid, ``n_landscapes``, image resolution, birth/death ranges,
  ``sigma`` and the weighting exponent are conventional choices. Two callers
  with different parameters get different vectors for the same network; that
  sensitivity is real and is not hidden by any default.
* **Persistence images are not injective.** Different diagrams can map to the
  same vector. Gaussian smoothing and binning discard information and the map
  cannot be inverted even in principle.
* **No statistical test of significance is attached to any coordinate.** A
  non-zero value is not evidence that a feature matters. The landscape and the
  image are representations, not tests.
* **No general simplicial reduction is implemented.** Pair extraction is the
  union-find/Kruskal argument above, which is exact for a graph and only for a
  graph. There is no boundary-matrix reduction, no GUDHI/Ripser dependency and
  no persistence over an arbitrary filtered complex.

References
----------

Bubenik, P. (2015). Statistical topological data analysis using persistence
landscapes. *JMLR* 16, 77-102.

Adams, H. et al. (2017). Persistence images: a stable vector representation of
persistent homology. *JMLR* 18(8), 1-35.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np

# The private helpers are imported deliberately. Re-deriving the edge set from
# the adjacency matrix here would create a second definition of "which edges
# exist and which are strong enough", which is exactly how two modules drift
# apart. ``_as_adjacency`` and ``_edges`` are the one definition.
from backend.modules.engine.persistent_homology import (
    UnionFind,
    _as_adjacency,
    _edges,
    merge_levels,
    topological_signature,
)

__all__ = [
    "PersistenceDiagram",
    "GraphDiagrams",
    "PersistenceVectorParameters",
    "SUMMARY_FEATURES",
    "SUMMARY_WIDTH",
    "diagram_from_graph",
    "persistence_landscape",
    "persistence_image",
    "topological_feature_vector",
    "persistence_vector",
]

# The summary block is a fixed list so its layout can be asserted, not guessed.
# ``connectivity_threshold`` is deliberately absent: it is ``inf`` for a
# disconnected network, and a non-finite entry is not a usable model feature.
# ``max_merge_level`` is the finite quantity that carries the same information
# whenever at least one merge exists (edge weights are strictly positive, so a
# value of 0.0 unambiguously means "no merge happened").
SUMMARY_FEATURES: Tuple[str, ...] = (
    "n_nodes",
    "n_edges",
    "beta_0",
    "beta_1",
    "largest_component_fraction",
    "fragmentation",
    "redundancy",
    "max_edge_weight",
    "max_merge_level",
    "n_h0_features",
    "n_h1_features",
)
SUMMARY_WIDTH = len(SUMMARY_FEATURES)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _finite_scalar(value: Any, name: str) -> float:
    """Coerce to a finite float or raise.

    A missing or non-finite input is never replaced by a default: every number
    this module emits must be traceable to an input, so a NaN here is a bug in
    the caller and is reported as one.
    """
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a real number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a real number, got {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


def _check_range(bounds: Sequence[float], name: str) -> Tuple[float, float]:
    values = tuple(bounds)
    if len(values) != 2:
        raise ValueError(f"{name} must be a (low, high) pair, got {values!r}")
    low = _finite_scalar(values[0], f"{name}[0]")
    high = _finite_scalar(values[1], f"{name}[1]")
    if not low < high:
        raise ValueError(f"{name} must satisfy low < high, got ({low}, {high})")
    return low, high


# ---------------------------------------------------------------------------
# Diagrams
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PersistenceDiagram:
    """Birth-death pairs for one homology dimension, birth <= death.

    The coordinate is the ascending filtration value ``s`` described in the
    module docstring. For a diagram built from a graph, ``s = W_max - t``; for a
    caller-supplied diagram the numbers are whatever filtration the caller is
    using, as long as they are finite and ``death >= birth``.

    The arrays are stored as float ``numpy`` arrays and are not made read-only,
    so a caller can mutate them in place; treat the object as immutable.
    """

    dimension: int
    birth: np.ndarray
    death: np.ndarray

    def __post_init__(self) -> None:
        if self.dimension not in (0, 1):
            raise ValueError(
                f"only H0 and H1 are supported, got dimension {self.dimension!r}"
            )
        birth = np.asarray(self.birth, dtype=float).reshape(-1)
        death = np.asarray(self.death, dtype=float).reshape(-1)
        if birth.shape != death.shape:
            raise ValueError(
                f"birth and death must have the same length, got "
                f"{birth.shape[0]} and {death.shape[0]}"
            )
        if not np.all(np.isfinite(birth)) or not np.all(np.isfinite(death)):
            raise ValueError(
                "birth and death must all be finite; a missing or non-finite "
                "pair is rejected rather than interpolated"
            )
        if np.any(death < birth):
            offending = int(np.argmax(death < birth))
            raise ValueError(
                f"death {death[offending]!r} is strictly before birth "
                f"{birth[offending]!r} at pair {offending}; the ascending "
                "filtration coordinate requires birth <= death"
            )
        object.__setattr__(self, "birth", birth)
        object.__setattr__(self, "death", death)

    @classmethod
    def from_pairs(
        cls, dimension: int, pairs: Iterable[Sequence[float]]
    ) -> "PersistenceDiagram":
        """Build a diagram from ``(birth, death)`` pairs.

        An empty iterable is allowed and produces an empty diagram: a tree has
        no H1 features, so emptiness is a well-defined state rather than an
        error. Every pair is validated by ``__post_init__``.
        """
        births: List[float] = []
        deaths: List[float] = []
        for index, pair in enumerate(pairs):
            values = tuple(pair)
            if len(values) != 2:
                raise ValueError(
                    f"pair {index} must have exactly two entries, got {len(values)}"
                )
            births.append(_finite_scalar(values[0], f"pair {index} birth"))
            deaths.append(_finite_scalar(values[1], f"pair {index} death"))
        return cls(
            dimension=dimension,
            birth=np.asarray(births, dtype=float),
            death=np.asarray(deaths, dtype=float),
        )

    @property
    def n_features(self) -> int:
        return int(self.birth.size)

    @property
    def persistence(self) -> np.ndarray:
        """Lifetimes ``death - birth``; zero for a trivial pair."""
        return self.death - self.birth


@dataclass(frozen=True)
class GraphDiagrams:
    """The H0 and H1 diagrams of one weighted graph, plus the bookkeeping.

    ``n_essential_h0`` is the number of components that never merge inside the
    domain, i.e. the components present at ``s = W_max``. They are essential
    classes and are deliberately not emitted as diagram points, because their
    persistence is infinite and fabricating a finite death for them would
    overstate the structure.
    """

    h0: PersistenceDiagram
    h1: PersistenceDiagram
    max_edge_weight: float
    n_nodes: int
    n_essential_h0: int


def diagram_from_graph(adjacency: Any) -> GraphDiagrams:
    """Extract the H0 and H1 persistence diagrams of a weighted graph.

    Args:
        adjacency: A square non-negative weight matrix or a multiplex layer, in
            any form ``persistent_homology._as_adjacency`` accepts. Zero means
            "no relation"; positive means a relation of that strength.

    Returns:
        A :class:`GraphDiagrams`. H0 deaths come from
        ``persistent_homology.merge_levels`` so that the two modules can never
        disagree about a merge. H1 births are the weights of the edges the
        descending-weight spanning forest rejects, each of which closes exactly
        one independent cycle; their death is the domain ceiling (see module
        docstring).

    The reflected coordinate uses ``W_max``, the largest edge weight. A graph
    with no edges yields two empty diagrams.
    """
    matrix = _as_adjacency(adjacency)
    n = int(matrix.shape[0])

    positive = matrix[matrix > 0]
    max_weight = float(positive.max()) if positive.size else 0.0

    # H0: reuse the module's merge levels rather than running a second Kruskal
    # pass for the same quantity. Levels come back in descending weight order.
    levels = merge_levels(matrix)
    h0 = PersistenceDiagram.from_pairs(
        0, [(0.0, max_weight - float(level)) for level in levels]
    )

    # H1: one union-find pass in the same descending-weight order. An edge that
    # merges nothing closes one cycle and is born at its own (weakest-in-cycle)
    # weight.
    forest = UnionFind(n)
    births: List[float] = []
    for u, v, weight in sorted(_edges(matrix, 0.0), key=lambda item: -item[2]):
        if forest.union(u, v):
            continue
        births.append(max_weight - float(weight))
    h1 = PersistenceDiagram.from_pairs(1, [(birth, max_weight) for birth in births])

    return GraphDiagrams(
        h0=h0,
        h1=h1,
        max_edge_weight=max_weight,
        n_nodes=n,
        n_essential_h0=n - len(levels),
    )


# ---------------------------------------------------------------------------
# Persistence landscapes (Bubenik 2015)
# ---------------------------------------------------------------------------

def persistence_landscape(
    diagram: PersistenceDiagram,
    grid: Sequence[float],
    n_landscapes: int,
) -> np.ndarray:
    """Sample the first ``n_landscapes`` landscape functions on ``grid``.

    For a pair ``(b, d)`` the tent function is

        ``psi(t) = max(0, min(t - b, d - t))``

    which is the standard ``Lambda(t) = max(0, min(t - b, d - t))`` of Bubenik
    (2015). (The usual statement writes the birth first because the coordinate
    is ascending here; the formula is exactly the textbook one.) The ``k``-th
    landscape is the ``k``-th largest tent value at each grid point,

        ``lambda_k(t) = k-th largest { psi_i(t) }``.

    Args:
        diagram: The birth-death pairs.
        grid: Caller-supplied filtration values, in the diagram's coordinate.
        n_landscapes: How many order statistics to return; must be >= 1.

    Returns:
        An ``(n_landscapes, len(grid))`` array. Lambda_k >= Lambda_{k+1} holds
        pointwise by construction, every entry is >= 0, and rows beyond the
        number of pairs are identically zero. An empty diagram therefore gives
        an all-zero array of the right shape -- a well-defined result, not an
        error, because "no features" is a legitimate state.
    """
    values = np.asarray(grid, dtype=float).reshape(-1)
    if values.size == 0:
        raise ValueError("grid must contain at least one filtration value")
    if not np.all(np.isfinite(values)):
        raise ValueError("grid must be finite")
    if isinstance(n_landscapes, bool) or not isinstance(n_landscapes, (int, np.integer)):
        raise ValueError(f"n_landscapes must be an integer, got {n_landscapes!r}")
    if int(n_landscapes) < 1:
        raise ValueError(f"n_landscapes must be at least 1, got {n_landscapes}")

    birth = diagram.birth[:, None]
    death = diagram.death[:, None]
    point = values[None, :]
    tents = np.maximum(0.0, np.minimum(point - birth, death - point))

    ordered = np.sort(tents, axis=0)[::-1, :]
    result = np.zeros((int(n_landscapes), values.size), dtype=float)
    count = min(int(n_landscapes), ordered.shape[0])
    if count:
        result[:count] = ordered[:count]
    return result


# ---------------------------------------------------------------------------
# Persistence images (Adams et al. 2017)
# ---------------------------------------------------------------------------

def persistence_image(
    diagram: PersistenceDiagram,
    *,
    resolution: int,
    birth_range: Sequence[float],
    death_range: Sequence[float],
    sigma: float,
    persistence_power: float = 1.0,
) -> np.ndarray:
    """Flattened weighted Gaussian-sum persistence image.

    The image is evaluated on a ``resolution x resolution`` grid of bin centres.
    With ``res`` bins over ``[lo, hi]`` the ``i``-th centre is

        ``c_i = lo + (i + 0.5) * (hi - lo) / res``

    and for diagram points ``(b_p, d_p)`` the image entry at birth bin ``i``
    and death bin ``j`` is

        ``I[i, j] = sum_p w_p * exp( -( (c^b_i - b_p)^2 + (c^d_j - d_p)^2 )
                                      / (2 * sigma^2) )``

    with the weight ``w_p = (d_p - b_p) ** persistence_power``. This is the
    Gaussian-smoothed, persistence-weighted sum of Adams et al. (2017) written
    on the birth-death plane; no normalisation and no clipping of out-of-range
    points is performed, so a feature outside the requested ranges still
    contributes its Gaussian tail rather than being silently dropped.

    Args:
        diagram: The birth-death pairs.
        resolution: Number of bins per axis; must be >= 1.
        birth_range: ``(low, high)`` extent of the birth axis, ``low < high``.
        death_range: ``(low, high)`` extent of the death axis, ``low < high``.
        sigma: Gaussian bandwidth in the same units as the diagram; must be > 0.
        persistence_power: Exponent applied to each lifetime before weighting;
            must be > 0. ``1.0`` weights by lifetime exactly.

    Returns:
        A ``resolution**2`` float array in C order, so entry
        ``i * resolution + j`` is birth bin ``i``, death bin ``j``. Every entry
        is >= 0 because lifetimes are non-negative and the Gaussian is positive.
        An empty diagram returns zeros of the documented fixed width. The map
        is not injective: distinct diagrams can produce the same vector.
    """
    if isinstance(resolution, bool) or not isinstance(resolution, (int, np.integer)):
        raise ValueError(f"resolution must be an integer, got {resolution!r}")
    resolution = int(resolution)
    if resolution < 1:
        raise ValueError(f"resolution must be at least 1, got {resolution}")

    birth_low, birth_high = _check_range(birth_range, "birth_range")
    death_low, death_high = _check_range(death_range, "death_range")

    bandwidth = _finite_scalar(sigma, "sigma")
    if bandwidth <= 0:
        raise ValueError(f"sigma must be positive, got {bandwidth}")

    power = _finite_scalar(persistence_power, "persistence_power")
    if power <= 0:
        raise ValueError(f"persistence_power must be positive, got {power}")

    birth_edges = np.linspace(birth_low, birth_high, resolution + 1)
    death_edges = np.linspace(death_low, death_high, resolution + 1)
    birth_centres = 0.5 * (birth_edges[:-1] + birth_edges[1:])
    death_centres = 0.5 * (death_edges[:-1] + death_edges[1:])

    if diagram.n_features == 0:
        return np.zeros(resolution * resolution, dtype=float)

    weights = np.power(diagram.persistence, power)
    offset_birth = birth_centres[:, None] - diagram.birth[None, :]
    offset_death = death_centres[:, None] - diagram.death[None, :]
    exponent = -(
        offset_birth[:, None, :] ** 2 + offset_death[None, :, :] ** 2
    ) / (2.0 * bandwidth * bandwidth)
    image = np.tensordot(np.exp(exponent), weights, axes=([2], [0]))
    return np.asarray(image, dtype=float).reshape(-1)


# ---------------------------------------------------------------------------
# Fixed-width feature vectors
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PersistenceVectorParameters:
    """Parameters that fix the width and layout of a persistence vector.

    Every field is a caller choice. There is no data-driven selector for any of
    them (see the module docstring), so the same network can legitimately yield
    different vectors under different parameters.
    """

    grid: np.ndarray
    n_landscapes: int
    image_resolution: int
    birth_range: Tuple[float, float]
    death_range: Tuple[float, float]
    sigma: float
    persistence_power: float = 1.0
    reference: str = "median"

    def __post_init__(self) -> None:
        grid = np.asarray(self.grid, dtype=float).reshape(-1)
        if grid.size == 0:
            raise ValueError("grid must contain at least one filtration value")
        if not np.all(np.isfinite(grid)):
            raise ValueError("grid must be finite")
        if isinstance(self.n_landscapes, bool) or not isinstance(
            self.n_landscapes, (int, np.integer)
        ):
            raise ValueError(
                f"n_landscapes must be an integer, got {self.n_landscapes!r}"
            )
        if int(self.n_landscapes) < 1:
            raise ValueError(
                f"n_landscapes must be at least 1, got {self.n_landscapes}"
            )
        if isinstance(self.image_resolution, bool) or not isinstance(
            self.image_resolution, (int, np.integer)
        ):
            raise ValueError(
                f"image_resolution must be an integer, got {self.image_resolution!r}"
            )
        if int(self.image_resolution) < 1:
            raise ValueError(
                f"image_resolution must be at least 1, got {self.image_resolution}"
            )
        _check_range(self.birth_range, "birth_range")
        _check_range(self.death_range, "death_range")
        bandwidth = _finite_scalar(self.sigma, "sigma")
        if bandwidth <= 0:
            raise ValueError(f"sigma must be positive, got {bandwidth}")
        power = _finite_scalar(self.persistence_power, "persistence_power")
        if power <= 0:
            raise ValueError(f"persistence_power must be positive, got {power}")
        if self.reference not in ("max", "median", "zero"):
            raise ValueError(
                "reference must be one of 'max', 'median', 'zero', "
                f"got {self.reference!r}"
            )
        object.__setattr__(self, "grid", grid)

    @property
    def n_grid(self) -> int:
        return int(self.grid.size)

    @property
    def landscape_width(self) -> int:
        return int(self.n_landscapes) * self.n_grid

    @property
    def image_width(self) -> int:
        return int(self.image_resolution) ** 2

    @property
    def topological_width(self) -> int:
        """Width of the landscape+image block, i.e. without summary statistics."""
        return 2 * self.landscape_width + 2 * self.image_width

    @property
    def width(self) -> int:
        return self.topological_width + SUMMARY_WIDTH

    def layout(self) -> Dict[str, slice]:
        """The documented slice of each block inside the vector.

        Layout, in order:

        * ``h0_landscape`` -- H0 landscape samples, C-order,
          ``n_landscapes x n_grid``.
        * ``h1_landscape`` -- H1 landscape samples, same shape.
        * ``h0_image`` -- H0 persistence image, C-order,
          ``image_resolution x image_resolution``.
        * ``h1_image`` -- H1 persistence image, same shape.
        * ``summary`` -- the :data:`SUMMARY_FEATURES` block, in that order.

        Only H1 carries the cycle/redundancy signal that motivates the module;
        the H0 blocks are included because fragmentation is the other half of
        the story and a caller may want to ablate them.
        """
        first = 0
        blocks: Dict[str, slice] = {}
        for name, size in (
            ("h0_landscape", self.landscape_width),
            ("h1_landscape", self.landscape_width),
            ("h0_image", self.image_width),
            ("h1_image", self.image_width),
            ("summary", SUMMARY_WIDTH),
        ):
            blocks[name] = slice(first, first + size)
            first += size
        return blocks


def _image_kwargs(parameters: PersistenceVectorParameters) -> Dict[str, Any]:
    return {
        "resolution": parameters.image_resolution,
        "birth_range": parameters.birth_range,
        "death_range": parameters.death_range,
        "sigma": parameters.sigma,
        "persistence_power": parameters.persistence_power,
    }


def topological_feature_vector(
    h0: PersistenceDiagram,
    h1: PersistenceDiagram,
    parameters: PersistenceVectorParameters,
) -> np.ndarray:
    """Landscape and image blocks only, without any summary statistics.

    Width is ``parameters.topological_width``. This is the piece of the vector
    that depends only on the diagram, so it is the one to use when the question
    is how a change in topology moves the representation, independent of any
    change in node or edge counts.
    """
    if h0.dimension != 0 or h1.dimension != 1:
        raise ValueError(
            "expected an H0 diagram first and an H1 diagram second, got "
            f"dimensions {h0.dimension} and {h1.dimension}"
        )
    h0_landscape = persistence_landscape(
        h0, parameters.grid, parameters.n_landscapes
    ).reshape(-1)
    h1_landscape = persistence_landscape(
        h1, parameters.grid, parameters.n_landscapes
    ).reshape(-1)
    h0_image = persistence_image(h0, **_image_kwargs(parameters))
    h1_image = persistence_image(h1, **_image_kwargs(parameters))
    return np.concatenate([h0_landscape, h1_landscape, h0_image, h1_image])


def _summary_block(
    adjacency: Any, diagrams: GraphDiagrams, reference: str
) -> np.ndarray:
    matrix = _as_adjacency(adjacency)
    signature = topological_signature(matrix, reference=reference)
    levels = merge_levels(matrix)
    # Levels are descending, so the first is the largest. Zero is an
    # unambiguous "no merge" because edge weights are strictly positive.
    max_merge = float(levels[0]) if levels else 0.0

    values = np.asarray(
        [
            float(signature.n_nodes),
            float(signature.n_edges),
            float(signature.beta_0),
            float(signature.beta_1),
            float(signature.largest_component_fraction),
            float(signature.fragmentation),
            float(signature.redundancy),
            float(signature.max_edge_weight),
            max_merge,
            float(diagrams.h0.n_features),
            float(diagrams.h1.n_features),
        ],
        dtype=float,
    )
    if values.size != SUMMARY_WIDTH or not np.all(np.isfinite(values)):
        raise ValueError(
            "summary block must be finite and of fixed width; this is a bug"
        )
    return values


def persistence_vector(
    adjacency: Any,
    parameters: PersistenceVectorParameters,
) -> np.ndarray:
    """Fixed-width feature vector for a weighted graph.

    Concatenates, in the order given by :meth:`PersistenceVectorParameters.layout`:
    the H0 and H1 landscape samples, the H0 and H1 persistence images, and the
    :data:`SUMMARY_FEATURES` block built from
    ``persistent_homology.topological_signature``. The width is
    ``parameters.width`` for every input, which is what the downstream model
    needs; an isolated node or a graph with no edges still yields a full-width
    finite vector.

    This function is deterministic: identical inputs give bit-identical output.
    Nothing here is stochastic, so there is no seed to pass.
    """
    diagrams = diagram_from_graph(adjacency)
    topological = topological_feature_vector(diagrams.h0, diagrams.h1, parameters)
    summary = _summary_block(adjacency, diagrams, parameters.reference)
    vector = np.concatenate([topological, summary])
    if vector.size != parameters.width:
        raise ValueError(
            f"vector width {vector.size} does not match the declared "
            f"width {parameters.width}; this is a bug"
        )
    return vector
