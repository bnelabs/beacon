"""Guard: the base API process must not import torch at startup.

The heavy ML runtime (torch, and the engine modules that wrap it) belongs to the
Celery workers and to the specific request handlers that run inference -- not to
the web process that serves the catalogue, config, results and dashboard reads.
Importing ``backend.api.main`` used to drag torch in transitively (route modules
imported the prediction engine, the config service probed CUDA at import time,
the results generator imported the engine orchestrator for type hints). That
inflated the base container footprint and risked memory starvation next to the
workers.

This test statically walks the *runtime* module-level import graph from
``backend.api.main`` -- following top-level ``import``/``from`` statements (and
top-level ``if``/``try``), but NOT function/class bodies (lazy) and NOT
``if TYPE_CHECKING:`` blocks (False at runtime) -- and asserts no reachable
module imports torch/tensorflow at module scope.

It is pure AST: it never imports the app, never needs torch/fastapi/pandas, and
runs in well under a second, so it is safe to run in any CI lane.
"""

from __future__ import annotations

import ast
import os
from collections import deque
from typing import Dict, Iterator, List, Optional, Tuple

_HEAVY = ("torch", "tensorflow")
_START = "backend.api.main"

# Repo root = two levels up from this file (backend/tests/).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mod_to_path(mod: str) -> Optional[str]:
    rel = os.path.join(*mod.split("."))
    for cand in (rel + ".py", os.path.join(rel, "__init__.py")):
        full = os.path.join(_REPO_ROOT, cand)
        if os.path.exists(full):
            return full
    return None


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


def _runtime_top(body: List[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield statements that execute at import time (module scope)."""
    for n in body:
        if isinstance(n, ast.If):
            if _is_type_checking(n.test):
                yield from _runtime_top(n.orelse)  # body is not runtime; else is
            else:
                yield from _runtime_top(n.body)
                yield from _runtime_top(n.orelse)
        elif isinstance(n, ast.Try):
            yield from _runtime_top(n.body)
            for h in n.handlers:
                yield from _runtime_top(h.body)
            yield from _runtime_top(n.orelse)
            yield from _runtime_top(n.finalbody)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # lazy bodies
        else:
            yield n


def _imports(tree: ast.Module) -> List[Tuple[str, Optional[str], int, Optional[List[str]]]]:
    out = []
    for n in _runtime_top(tree.body):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.append(("abs", a.name, 0, None))
        elif isinstance(n, ast.ImportFrom):
            out.append(("from", n.module, n.level or 0, [a.name for a in n.names]))
    return out


def _heavy(tree: ast.Module) -> List[str]:
    hits = []
    for n in _runtime_top(tree.body):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] in _HEAVY:
                    hits.append(a.name)
        elif isinstance(n, ast.ImportFrom):
            if n.level == 0 and n.module and n.module.split(".")[0] in _HEAVY:
                hits.append(n.module)
    return hits


def _resolve(cur_mod: str, item) -> List[str]:
    kind, name, level, subs = item
    out: List[str] = []
    if kind == "abs":
        if name.startswith("backend"):
            out.append(name)
    else:
        if level and level > 0:
            pkg = cur_mod.split(".")[:-1]
            up = pkg[: len(pkg) - (level - 1)]
            target = ".".join(up + ([name] if name else []))
        else:
            target = name or ""
        if target.startswith("backend"):
            out.append(target)
            for s in subs or []:
                out.append(f"{target}.{s}")
    return out


def _scan(start: str = _START) -> Tuple[Dict[str, Optional[str]], Dict[str, List[str]]]:
    seen: Dict[str, Optional[str]] = {start: None}
    heavy: Dict[str, List[str]] = {}
    q = deque([start])
    while q:
        mod = q.popleft()
        path = _mod_to_path(mod)
        if not path:
            continue
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        h = _heavy(tree)
        if h:
            heavy[mod] = h
        for item in _imports(tree):
            for d in _resolve(mod, item):
                if d not in seen and _mod_to_path(d):
                    seen[d] = mod
                    q.append(d)
    return seen, heavy


def test_api_startup_does_not_import_torch():
    """No module reachable from backend.api.main may import torch at module scope."""
    seen, heavy = _scan()
    assert _mod_to_path(_START), f"could not locate {_START} from {_REPO_ROOT}"
    if heavy:
        chains = []
        for m, h in sorted(heavy.items()):
            chain, cur = [], m
            while cur is not None:
                chain.append(cur)
                cur = seen[cur]
            chains.append(f"{m} imports {h}\n      via: {' -> '.join(reversed(chain))}")
        raise AssertionError(
            "torch/tensorflow is imported at module level on the API startup path:\n  "
            + "\n  ".join(chains)
            + "\nMove the import inside the function that needs it (or under TYPE_CHECKING)."
        )


def test_known_heavy_route_modules_are_lazy():
    """The specific modules fixed for this invariant stay lazy at module scope."""
    targets = [
        "backend.api.routes.system",
        "backend.api.routes.models_v1",
        "backend.api.routes.network",
        "backend.services.config_service",
        "backend.modules.results.generator",
    ]
    for mod in targets:
        path = _mod_to_path(mod)
        assert path, f"missing {mod}"
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        assert not _heavy(tree), f"{mod} reintroduced a module-level torch/tf import"
        # engine imports at module scope would also drag torch in
        for item in _imports(tree):
            for dep in _resolve(mod, item):
                assert not dep.startswith("backend.modules.engine"), (
                    f"{mod} imports {dep} at module level; engine modules load torch"
                )


if __name__ == "__main__":
    test_api_startup_does_not_import_torch()
    test_known_heavy_route_modules_are_lazy()
    print("OK: API startup path is torch-free; heavy modules import lazily.")
