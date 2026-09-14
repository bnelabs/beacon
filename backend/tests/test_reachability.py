"""Reachability is a property of the system, so it gets a test.

This repository has now found the *same* defect three times: a module with a
complete implementation and a thorough test suite that no production code
imports. It happened to `liquidity_spiral` and `tncm_vae` (fixed, see
`docs/G_SIB_BUILD.md` §2.10), then again to `cpcv` and `neural_sde` (fixed, see
`docs/EXECUTIVE_REVIEW_REMEDIATION.md` §5.0), and a scan then found a dozen more.

The reason it keeps happening is structural: unit tests pass whether or not
anything calls the module, so a green suite cannot distinguish "this works" from
"this runs". Documentation is worse than useless in that state -- it advertises a
capability the system does not have, which is exactly what an auditor would rely
on.

So this file asserts the property directly, by walking the import graph from the
production entry points:

* every module in :data:`REQUIRED_REACHABLE` is reachable from a root;
* every module in :data:`KNOWN_UNREACHABLE` is not;
* **every unreachable production module is in the census** -- see
  :class:`TestCensusIsComplete`.

Why *transitive* and not "has an importer". An earlier draft of this file checked
direct importers and misclassified `temporal_graph`: it is imported, but only by
`neural_sde`, and for its memory primitives rather than its model. Reachability
has to be measured from the roots, or "imported by another orphan" reads as
reachable. That distinction is also why a module can be reachable and still
contribute nothing -- see :data:`UNUSED_SYMBOLS` for the class-level check.

The disposition census
----------------------

The first version of this file declared one flat orphan list. That turned out to
be the weaker half of the guard, for a reason worth recording: it asserted each
list *independently* -- "these are reachable", "these are not" -- but never that
the two covered the tree. So a new orphan could appear between them and nothing
failed. Two already had: `data/pit.py` (dead once its only importers, the
connectors, were dead) and `engine/foundation_encoders.py` (the Toto encoder,
reachable only from `scripts/compare_encoder_sizes.py`, a developer benchmark).
Both were missing from the census that claimed to have scanned the whole backend.

Every unreachable module now carries a :class:`Disposition`, so an orphan is a
queued decision rather than an anonymous entry:

``wire``
    A production home exists or is cheap to add. These are the next work items.
``decide``
    Blocked on a product or design call, not on effort. The blocker is named.
``park``
    No input exists and none is planned. Kept only because deletion is a
    decision too, and it is recorded here rather than left implicit.

Scope and limits. Importers are found statically with ``ast``, resolving relative
imports. That misses genuinely dynamic loading, which is why ``backend/plugins/*``
is excluded: plugins are resolved by name through ``get_plugin`` by design. A
dynamic registry whose entry point has no caller is *not* excluded, which is how
the connectors package was caught: ``build_connector`` was never called from
production even though the registry itself was dynamic. That layer has since been
deleted on the evidence -- see :data:`REMOVED` -- and
``docs/data_connectors.md`` keeps the findings. Reachability is a necessary
condition for a capability, not proof of usefulness.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, NamedTuple, Set, Tuple

BACKEND = Path(__file__).resolve().parents[1]

#: Modules that start the process: the FastAPI app, and the Celery app that
#: registers the job implementations. Anything not reachable from one of these
#: does not run in production.
PRODUCTION_ROOTS: Tuple[str, ...] = (
    "backend.api.main",
    "backend.tasks.celery_app",
)

#: Capability modules the system claims to run. Each must be reachable.
REQUIRED_REACHABLE: Dict[str, str] = {
    "backend.modules.engine.cpcv": "CPCV is selectable as the validation scheme",
    "backend.modules.engine.backtesting": "walk-forward and CPCV harnesses",
    "backend.modules.engine.trainer": "training entry point",
    "backend.modules.engine.prediction_engine": "inference entry point",
    "backend.modules.engine.model_io": "safe checkpoint loading",
    "backend.modules.engine.neural_sde": "latent stress puts the SDE on the engine path",
    "backend.modules.engine.latent_dynamics": "the SDE scenario the engine accepts",
    "backend.modules.data.fractional": "ADF/KPSS and fractional differencing",
    "backend.modules.data.quality_gate": "the data certification gate",
    "backend.modules.data.pit": "point-in-time exposure vintages behind the network graph (load_as_of)",
    "backend.modules.risk.clearing": "Eisenberg-Noe clearing",
    "backend.modules.risk.liquidity_spiral": "the spiral the clearing shortfall drives",
    "backend.modules.risk.bank_analyzer": "per-institution systemic analysis",
    "backend.modules.risk.fire_sale": "coupled fire-sale equilibrium",
    "backend.modules.risk.regulatory": "Basel III stress translation",
    "backend.modules.engine.persistence_vectors": "topological signature vectors",
    "backend.modules.engine.portfolio_overlap": "crowded-trade overlap",
    "backend.modules.engine.causal_discovery": "NOTEARS, linear and non-linear basis",
    "backend.modules.engine.tncm_vae": "abduction / intervention / propagation",
    "backend.modules.engine.counterfactual": "the counterfactual scenario the engine accepts",
}


class Disposition(NamedTuple):
    """What an unreachable module is waiting on, and what happens next.

    ``blocker`` is *why* it does not run, ``plan`` is the disposition class
    (``wire`` / ``decide`` / ``park``), and ``next_step`` is the concrete action
    that would move it. All three are required: an entry with no next step is the
    undifferentiated orphan this census exists to replace.
    """

    blocker: str
    plan: str
    next_step: str


#: Modules implemented, tested and *not* reachable from production. Recorded
#: rather than deleted, so the gap is visible instead of implied.
KNOWN_UNREACHABLE: Dict[str, Disposition] = {
    # -- wire: a production home exists or is cheap to add -------------------
    "backend.modules.engine.conformal": Disposition(
        blocker="the prediction engine reports no calibrated interval, but the seam is written down",
        plan="wire",
        next_step="build the calibrator in prediction_engine (prediction_engine.py:731 reports (None, None)) from a held-out window per source",
    ),
    "backend.modules.engine.hidden_markov": Disposition(
        blocker="a regime label is computed but never attached to a per-source score",
        plan="wire",
        next_step="attach the StudentTHMM regime label to the per-source score; this also supplies mixture_of_experts' missing regime input",
    ),
    "backend.modules.engine.mixture_of_experts": Disposition(
        blocker="regime-conditioned experts have no regime input",
        plan="wire",
        next_step="wire together with hidden_markov -- one integration retires both orphans",
    ),
    "backend.modules.data.network_gate": Disposition(
        blocker="the collector never calls the topology gate",
        plan="wire",
        next_step="call it at the collector's post-fetch step, where quality_gate is already applied",
    ),
    "backend.modules.results.timeseries_store": Disposition(
        blocker="nothing writes risk scores or metrics through it, though the infrastructure for it is already deployed",
        plan="wire",
        next_step="call record_risk_scores on job completion; TimescaleDB is already in docker-compose.yml, and the timescale_timeseries migration already builds the hypertables this store is the only consumer of",
    ),
    "backend.modules.engine.uncertainty": Disposition(
        blocker="nothing consumes a decomposed uncertainty signal",
        plan="wire",
        next_step="consume it after conformal: it answers the question conformal does not (is the interval wide because the world is noisy, or because the model is lost), and its docstring says an epistemic spike should refuse the prediction",
    ),
    # -- decide: blocked on a call, not on effort ----------------------------
    "backend.modules.engine.foundation_encoders": Disposition(
        blocker="the encoder contract, compose_input and the deterministic stand-in survive; the Toto wrapper and its dependency train were deleted in the 2026-09 hygiene round because no production path ever embedded a node with them",
        plan="decide",
        next_step="re-add a foundation model only in the same change that wires the engine path embedding nodes with it (the TemporalGraphNetwork in UNUSED_SYMBOLS); the dependency alone must never return",
    ),
    "backend.modules.engine.subgraphx": Disposition(
        blocker="attribution needs a game value over liability-network subsets, and nothing produces one",
        plan="decide",
        next_step="decide whether a game value is coming; prediction_engine.py:17 already declines to pass gradient*input off as one, so it cannot be improvised",
    ),
    "backend.modules.engine.causal_validation": Disposition(
        blocker="it validates a *pair* of graphs (declared against learned) and nothing produces both on a job result",
        plan="decide",
        next_step="decide where the declared-vs-learned comparison belongs in the product, then add the producer",
    ),
    "backend.modules.engine.event_metrics": Disposition(
        blocker="event precision/lead-time metrics need a labelled event target series, which the pipeline does not produce",
        plan="decide",
        next_step="decide whether a binary event target is in scope; if it is, the model-quality report is the home",
    ),
    # -- park: no input exists and none is planned ---------------------------
    "backend.modules.data.streaming": Disposition(
        blocker="no streaming source is configured and the only transport is an in-memory test double",
        plan="park",
        next_step="keep only because temporal_graph and two test files use it as a harness; delete if no streaming source lands",
    ),
    "backend.modules.engine.federated": Disposition(
        blocker="Bonawitz-style masking needs a multi-institution training coordinator owning the roster, model shape and transport; EngineOrchestrator and ModelTrainer are both single-node",
        plan="park",
        next_step="keep parked with the 'Reachability (honest status)' docstring; revisit only if a coordinator is funded",
    ),
}

#: Modules removed from the tree by the disposition census. Recorded so a removal
#: is a fact in the repository rather than a gap someone has to rediscover.
REMOVED: Dict[str, str] = {
    "backend.modules.engine.foundation_encoders.TotoEncoder": (
        "the Toto 2.0 wrapper, its local-weights resolution machinery and "
        "backend/scripts/compare_encoder_sizes.py, deleted in the 2026-09 "
        "hygiene round. Implemented and tested, but constructed only by the "
        "developer benchmark while every production image paid for toto-2 plus "
        "einops, gluonts[torch], safetensors, jaxtyping, dd-unit-scaling and "
        "huggingface-hub. The encoder contract, compose_input and "
        "HashedFallbackEncoder remain in the module and keep their tests."
    ),
    "backend.modules.explainability": (
        "empty package: __init__.py was zero bytes and nothing imported it. The "
        "explainability *routes* live in backend/api/routes/ and are unaffected."
    ),
    "backend.modules.data.connectors.base": (
        "the connector layer, deleted after the ecb_ccp migration spike. It had no "
        "production caller, none of its five feeds had an engine consumer at the "
        "granularity the engine needs, and the plugin interface it would have been "
        "bridged into cannot carry its two-clock guarantee -- fetch_indicator_data "
        "returns Date, Value, and observed_at/revision appear nowhere in "
        "backend/plugins/. docs/data_connectors.md keeps the findings."
    ),
    "backend.modules.data.connectors.bis_credit": "deleted with the connector layer; see connectors.base",
    "backend.modules.data.connectors.ecb_ccp": "deleted with the connector layer; see connectors.base",
    "backend.modules.data.connectors.payments": "deleted with the connector layer; see connectors.base",
    "backend.modules.data.connectors.sec_form_pf": "deleted with the connector layer; see connectors.base",
    "backend.modules.data.connectors.sec_n_mfp": "deleted with the connector layer; see connectors.base",
}

#: Modules deliberately outside the census. Excluding by rule rather than by
#: omission is the point: an unlisted module is indistinguishable from a
#: forgotten one, which is how the two omissions above happened.
EXCLUDED_FROM_CENSUS: Dict[str, str] = {
    "backend.plugins": (
        "resolved by name through get_plugin, so static imports cannot see the "
        "live path; the registry itself has live callers (collector.py, "
        "data_source_service.py), which is what makes these not orphans"
    ),
    "backend.alembic": "migrations are not capabilities",
    "backend.scripts": "developer entry points, not production entry points",
}

#: Classes whose *module* is reachable but whose class is referenced nowhere
#: outside its own file. This is the finer-grained version of the same defect and
#: the reason module reachability alone is not enough.
UNUSED_SYMBOLS: Dict[str, Tuple[str, str]] = {
    "backend.modules.engine.temporal_graph": (
        "TemporalGraphNetwork",
        "the event-stream model. The module is reachable because neural_sde reuses "
        "its memory primitives, but nothing constructs the network itself.",
    ),
}


def _module_name(path: Path) -> str:
    """Dotted module name for a file, relative to the repository root."""
    relative = path.relative_to(BACKEND.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _iter_source_files():
    for path in BACKEND.rglob("*.py"):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        yield path


def _imported_names(path: Path, module: str) -> Set[str]:
    """Every module name imported by ``path``, resolving relative imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    own_package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = own_package
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0]
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            found.add(target)
            # `from pkg import submodule` also imports pkg.submodule.
            found.update(f"{target}.{alias.name}" for alias in node.names)
    return found


def _build_import_graph():
    """Return (defined modules, module -> modules it imports)."""
    defined: Set[str] = set()
    imports: Dict[str, Set[str]] = {}

    for path in _iter_source_files():
        module = _module_name(path)
        defined.add(module)
        imports[module] = _imported_names(path, module)

    # Keep only edges between modules that exist, minus self-edges.
    cleaned: Dict[str, Set[str]] = {}
    for module, targets in imports.items():
        cleaned[module] = {t for t in targets if t in defined and t != module}
    return defined, cleaned


def _reachable_from_roots(imports: Dict[str, Set[str]]) -> Set[str]:
    seen: Set[str] = set()
    stack = [root for root in PRODUCTION_ROOTS if root in imports]
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        stack.extend(imports.get(module, ()))
    return seen


def _referenced_identifiers(excluding: str) -> Set[str]:
    """Identifiers referenced anywhere outside tests and outside ``excluding``."""
    names: Set[str] = set()
    for path in _iter_source_files():
        module = _module_name(path)
        if module == excluding:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add(node.name.rsplit(".", 1)[-1])
                if node.asname:
                    names.add(node.asname)
    return names


_DEFINED, _IMPORTS = _build_import_graph()
_REACHABLE = _reachable_from_roots(_IMPORTS)


def _is_package(module: str) -> bool:
    """True when the module name denotes a directory (a package), not a file."""
    return (BACKEND.parent / Path(*module.split("."))).is_dir()


def _is_excluded(module: str) -> bool:
    return any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in EXCLUDED_FROM_CENSUS
    )


def _census_universe() -> Set[str]:
    """Every production module the census is responsible for covering.

    Packages, the roots themselves and the declared exclusions are not
    capabilities, so they are outside the universe rather than silently absent
    from it.
    """
    prefixes = ("backend.modules.", "backend.services.", "backend.api.", "backend.tasks.")
    return {
        module
        for module in _DEFINED
        if module.startswith(prefixes)
        and not _is_package(module)
        and not _is_excluded(module)
    }


class TestReachabilityFromProductionRoots:
    """Every claimed capability must be reachable from a process entry point."""

    def test_the_roots_themselves_exist(self):
        missing = sorted(root for root in PRODUCTION_ROOTS if root not in _DEFINED)
        assert not missing, f"production roots not found in the tree: {missing}"

    def test_every_required_module_exists(self):
        missing = sorted(set(REQUIRED_REACHABLE) - _DEFINED)
        assert not missing, (
            f"{missing} are listed as required-reachable but do not exist; the "
            "census has drifted from the tree"
        )

    def test_each_required_module_is_reachable(self):
        unreachable = {
            module: reason
            for module, reason in REQUIRED_REACHABLE.items()
            if module not in _REACHABLE
        }
        assert not unreachable, (
            "these modules are claimed as production capabilities but are not "
            f"reachable from {PRODUCTION_ROOTS}: {unreachable}"
        )


class TestCensusIsComplete:
    """An incomplete census is the defect this file exists to prevent.

    The first version asserted both lists independently and never that their
    union covered the tree, so new orphans could appear in the gap. Two had.
    """

    def test_every_unreachable_production_module_is_in_the_census(self):
        unlisted = sorted(_census_universe() - _REACHABLE - set(KNOWN_UNREACHABLE))
        assert not unlisted, (
            f"{unlisted} are unreachable from {PRODUCTION_ROOTS} but appear in "
            "neither REQUIRED_REACHABLE nor KNOWN_UNREACHABLE. Add each to "
            "KNOWN_UNREACHABLE with a Disposition (blocker, plan, next_step), or "
            "wire it and promote it to REQUIRED_REACHABLE. Silence here is how "
            "data/pit.py and engine/foundation_encoders.py stayed invisible."
        )

    def test_the_census_does_not_record_modules_that_do_not_exist(self):
        # Only KNOWN_UNREACHABLE is checked here: a REMOVED entry is *expected*
        # to be absent from the tree, and test_removed_modules_do_not_reappear
        # is what stops it coming back.
        ghost = sorted(set(KNOWN_UNREACHABLE) - _DEFINED)
        assert not ghost, (
            f"the census names modules that are not in the tree: {ghost}. If one "
            "was deliberately deleted, move it to REMOVED with the reason."
        )

    def test_removed_modules_do_not_reappear(self):
        back = sorted(module for module in REMOVED if module in _DEFINED)
        assert not back, (
            f"{back} were removed by the disposition census but exist again. If "
            "one is genuinely reinstated, drop it from REMOVED and add it to "
            "KNOWN_UNREACHABLE or REQUIRED_REACHABLE."
        )


class TestDispositionsAreRecorded:
    """Every orphan must be a queued decision, not an anonymous entry."""

    VALID_PLANS = ("wire", "decide", "park")

    def test_every_orphan_has_a_verdict(self):
        incomplete = {
            module: record
            for module, record in KNOWN_UNREACHABLE.items()
            if record.plan not in self.VALID_PLANS
            or not record.blocker.strip()
            or not record.next_step.strip()
        }
        assert not incomplete, (
            "these orphans carry no usable disposition; each needs a plan in "
            f"{self.VALID_PLANS} plus a non-empty blocker and next_step: "
            f"{sorted(incomplete)}"
        )

    def test_the_verdicts_are_counted_where_a_reader_will_see_them(self):
        """The docstring claims three registers; this fails if that drifts."""
        counted = {
            plan: sum(1 for record in KNOWN_UNREACHABLE.values() if record.plan == plan)
            for plan in self.VALID_PLANS
        }
        assert sum(counted.values()) == len(KNOWN_UNREACHABLE)
        assert counted["wire"] > 0, "no orphan is queued for wiring, which is the point of the census"


class TestKnownUnreachableStaysHonest:
    """The recorded orphans must really be orphans, or the census is a lie."""

    def test_every_known_orphan_exists(self):
        missing = sorted(set(KNOWN_UNREACHABLE) - _DEFINED)
        assert not missing, f"census lists modules that no longer exist: {missing}"

    def test_no_known_orphan_has_quietly_become_reachable(self):
        """If one is wired, this fails so the entry is promoted, not forgotten."""
        now_reachable = sorted(
            module for module in KNOWN_UNREACHABLE if module in _REACHABLE
        )
        assert not now_reachable, (
            f"these modules were recorded as orphans but are now reachable: "
            f"{now_reachable}. Move them into REQUIRED_REACHABLE so the census "
            "reflects what the system actually runs."
        )

    def test_the_two_lists_do_not_overlap(self):
        assert not (set(REQUIRED_REACHABLE) & set(KNOWN_UNREACHABLE))


class TestUnusedSymbols:
    """A reachable module can still contribute nothing. Check the class too."""

    def test_the_recorded_symbols_are_still_unused(self):
        for module, (symbol, reason) in UNUSED_SYMBOLS.items():
            assert module in _DEFINED, f"{module} no longer exists"
            referenced = _referenced_identifiers(excluding=module)
            assert symbol not in referenced, (
                f"{module}.{symbol} was recorded as unused but is now referenced "
                f"({reason}) -- remove it from UNUSED_SYMBOLS and, if it is wired, "
                "add the module to REQUIRED_REACHABLE."
            )
