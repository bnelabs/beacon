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
* every module in :data:`KNOWN_UNREACHABLE` is not.

The second assertion is what keeps the census honest. If someone wires one of the
known orphans, this test fails and forces the entry to move up into
:data:`REQUIRED_REACHABLE` -- so the census cannot rot into a stale claim, which
is the failure mode that produced the problem in the first place.

Why *transitive* and not "has an importer". An earlier draft of this file checked
direct importers and misclassified `temporal_graph`: it is imported, but only by
`neural_sde`, and for its memory primitives rather than its model. Reachability
has to be measured from the roots, or "imported by another orphan" reads as
reachable. That distinction is also why a module can be reachable and still
contribute nothing -- see :data:`UNUSED_SYMBOLS` for the class-level check.

Scope and limits. Importers are found statically with ``ast``, resolving relative
imports. That misses genuinely dynamic loading, which is why ``backend/plugins/*``
is excluded: plugins are resolved by name through ``get_plugin`` by design. A
dynamic registry whose entry point has no caller is *not* excluded -- the
connectors package is listed below, because ``build_connector`` is never called
from production even though the registry itself is dynamic. Reachability is a
necessary condition for a capability, not proof of usefulness.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Set, Tuple

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
    "backend.modules.risk.clearing": "Eisenberg-Noe clearing",
    "backend.modules.risk.liquidity_spiral": "the spiral the clearing shortfall drives",
    "backend.modules.risk.bank_analyzer": "per-institution systemic analysis",
    "backend.modules.risk.fire_sale": "coupled fire-sale equilibrium",
    "backend.modules.risk.regulatory": "Basel III stress translation",
    "backend.modules.engine.persistence_vectors": "topological signature vectors",
    "backend.modules.engine.portfolio_overlap": "crowded-trade overlap",
}

#: Modules implemented, tested and *not* reachable from production. Recorded
#: rather than deleted, so the gap is visible instead of implied. Each entry
#: carries what a real integration would need -- see the census in
#: `docs/EXECUTIVE_REVIEW_REMEDIATION.md`.
KNOWN_UNREACHABLE: Dict[str, str] = {
    "backend.modules.engine.conformal": "split conformal + ACI; the prediction engine already documents a pending conformal calibration step, so this is the first recommended wiring",
    "backend.modules.engine.federated": "Bonawitz-style masking; needs a federated training coordinator, which does not exist",
    "backend.modules.engine.hidden_markov": "Student-t regime detection; needs a regime label attached to the per-source score",
    "backend.modules.engine.uncertainty": "uncertainty helpers; superseded-or-pending relative to conformal",
    "backend.modules.engine.subgraphx": "attribution; needs a liability network and a game value on a job result",
    "backend.modules.engine.event_metrics": "event-precision metrics; needs an event target series in the pipeline",
    "backend.modules.engine.causal_validation": "counterfactual validation; the causal subsystem has no production entry point",
    "backend.modules.engine.causal_discovery": "NOTEARS DAG learning; imported only by causal_validation, which is itself unreachable, so it is loaded by nothing that runs",
    "backend.modules.engine.tncm_vae": "counterfactual VAE; reached only through the unreachable causal subsystem",
    "backend.modules.engine.mixture_of_experts": "regime-conditioned experts; needs a regime input",
    "backend.modules.data.network_gate": "network data-quality gate; not called by the collector",
    "backend.modules.data.streaming": "streaming ingestion; no streaming source is configured",
    "backend.modules.results.timeseries_store": "TimescaleDB store; no runtime caller writes through it",
    "backend.modules.data.connectors.bis_credit": "connector registry entry point (build_connector) has no production caller",
    "backend.modules.data.connectors.ecb_ccp": "connector registry entry point (build_connector) has no production caller",
    "backend.modules.data.connectors.payments": "connector registry entry point (build_connector) has no production caller",
    "backend.modules.data.connectors.sec_form_pf": "connector registry entry point (build_connector) has no production caller",
    "backend.modules.data.connectors.sec_n_mfp": "connector registry entry point (build_connector) has no production caller",
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
