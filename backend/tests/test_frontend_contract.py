"""The frontend's declared API contract must match the app's live schema.

The TypeScript migration gave the frontend typed interfaces for every payload
(``frontend/src/types/api.ts``) and typed hook calls
(``fetchApi<Job[]>('/v1/jobs')``). Types that nothing checks against the
server are documentation that rots: the migration's own founding incidents
(GlobalSearch reading ``id``/``model_name``/``version`` off a ModelSummary
that declares ``model_id``/``name``/``model_version``; a create-source form
that would not close because the endpoint 404'd) were field-name and envelope
drift that only an end-to-end run could see.

This test closes that loop at the source of truth. It:

1. extracts every typed ``fetchApi<T>``/``fetchJson<T>`` call in
   ``frontend/src`` (endpoint, method, bound type),
2. resolves the endpoint against the app's OWN ``app.openapi()`` — the same
   schema ``docs/api-endpoints.md`` is generated from, so a route change that
   updates the docs updates this check automatically,
3. parses the bound interface out of ``types/api.ts`` and asserts every field
   the frontend declares exists on the wire schema — recursing one level per
   nested interface/array so ``NotificationsResponse.notifications ->
   Notification`` is checked too,
4. and fails with the full list of violations, naming endpoint, type and
   field, rather than one at a time.

Endpoints whose backend response is ``Dict[str, Any]`` (analytics, data
quality, system status, the network graph) carry no machine-checkable shape;
they are counted and reported as untyped, not silently passed. Interfaces
with a ``[key: string]: unknown`` index signature (``ModelResultMetrics``,
``JobParameters``) are open by design and skipped for the same reason.

``ALLOWED_WIRE_EXCEPTIONS`` is the only escape hatch, and every entry carries
the transport that justifies it.

Runs in backend-tests.yml (nightly + dispatch): it imports the app, which is
torch-free at module scope but still the full route tree.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

os.environ.setdefault("USE_SQLITE", "true")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_SRC = _REPO_ROOT / "frontend" / "src"
_TYPES_FILE = _FRONTEND_SRC / "types" / "api.ts"

try:
    from backend.api.main import app  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - standalone fallback
    from api.main import app  # type: ignore


# ---------------------------------------------------------------------------
# Allowances: fields the frontend declares that the REST schema does not carry,
# with the transport that does. Nothing enters this dict without a reason.
# ---------------------------------------------------------------------------
ALLOWED_WIRE_EXCEPTIONS: Dict[Tuple[str, str], str] = {
    ("Job", "job_id"): (
        "The WebSocket job_update payload carries both id and job_id (see "
        "backend/api/job_events.py: the two React Query caches are keyed "
        "differently); WS updates are merged into cached REST rows, so the "
        "frontend type legitimately spans both transports. REST sends only id."
    ),
    ("Job", "error"): (
        "The WebSocket payload names the technical string 'error' "
        "(backend/api/job_events.py) while REST names it 'error_message'; "
        "JobDetails reads both spellings."
    ),
}

_PRIMITIVE_TYPE_NAMES = {
    "string", "number", "boolean", "unknown", "any", "null", "undefined",
    "Record", "Array", "Partial", "Date", "Set", "Map", "object",
}


# ---------------------------------------------------------------------------
# Frontend parsing
# ---------------------------------------------------------------------------

_CALL_RE = re.compile(
    r"fetch(?:Api|Json)\s*<\s*([A-Za-z0-9_]+)\s*(?:\[\s*\])?\s*>\s*\(\s*[`'\"]([^`'\"]*)[`'\"]"
)
_METHOD_RE = re.compile(r"method:\s*['\"`](\w+)['\"`]")


def _normalize_call_path(raw: str) -> Optional[str]:
    """Turn a template-literal call path into an OpenAPI-comparable path.

    Drops query strings, drops complex interpolations (a ``${...}`` whose
    contents are not a bare identifier — e.g. ``${queryString ? ... : ''}``),
    turns simple ``${param}`` segments into ``{*}`` wildcards, strips a
    leading ``${API_ORIGIN}``, and ensures the ``/api`` prefix fetchApi adds.
    """
    path = raw.split("?", 1)[0]
    cut = re.search(r"\$\{(?!\w+\})", path)
    if cut:
        path = path[: cut.start()]
    if path.startswith("${API_ORIGIN}"):
        path = path[len("${API_ORIGIN}"):]
    path = re.sub(r"\$\{\w+\}", "{*}", path)
    if "$" in path or not path.startswith("/"):
        return None
    if not path.startswith("/api"):
        path = "/api" + path
    return path.rstrip("/") or "/"


def _iter_source_files() -> Iterator[Path]:
    for path in sorted(_FRONTEND_SRC.rglob("*.ts*")):
        if path.suffix in (".ts", ".tsx") and not path.name.endswith(".d.ts"):
            yield path


def frontend_typed_calls() -> List[Dict[str, str]]:
    """Every typed fetchApi<T>/fetchJson<T> call with a literal path."""
    calls: List[Dict[str, str]] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        for match in _CALL_RE.finditer(text):
            type_name, raw_path = match.group(1), match.group(2)
            normalized = _normalize_call_path(raw_path)
            if normalized is None:
                continue
            # The method belongs to THIS call: stop the search window at the
            # next fetch call so a neighbour's options are not attributed
            # here (same windowing rule as scripts/check_e2e_api_coverage.mjs).
            tail = text[match.end(): match.end() + 400].split("fetchApi")[0].split("fetchJson")[0]
            method_match = _METHOD_RE.search(tail)
            calls.append({
                "type": type_name,
                "path": normalized,
                "method": (method_match.group(1) if method_match else "GET").lower(),
                "file": str(path.relative_to(_REPO_ROOT)),
            })
    return calls


def parse_ts_interfaces(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse `export interface X { ... }` blocks into field maps.

    Returns {name: {"fields": [field names at brace depth 1],
                    "types": {field: raw type text},
                    "open": bool (has an index signature)}}.
    Depth tracking keeps nested inline object literals out of the field list.
    """
    interfaces: Dict[str, Dict[str, Any]] = {}
    current: Optional[str] = None
    depth = 0
    fields: List[str] = []
    types: Dict[str, str] = {}
    is_open = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if current is None:
            m = re.match(r"export interface (\w+)", line)
            if m:
                current = m.group(1)
                fields, types, is_open = [], {}, False
                depth = line.count("{") - line.count("}")
            continue

        was_depth = depth
        depth += line.count("{") - line.count("}")
        if was_depth == 1 and not line.startswith(("//", "*", "/*")):
            fm = re.match(r"\[(\w+)\s*:\s*string\]", line)
            if fm:
                is_open = True
            else:
                fm = re.match(r"(\w+)(\??)\s*:\s*(.+)$", line)
                if fm:
                    fields.append(fm.group(1))
                    types[fm.group(1)] = fm.group(3)
        if depth <= 0:
            interfaces[current] = {"fields": fields, "types": types, "open": is_open}
            current = None
            depth = 0

    return interfaces


# ---------------------------------------------------------------------------
# OpenAPI resolution
# ---------------------------------------------------------------------------

def _deref(schema: Dict[str, Any], spec: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    while isinstance(schema, dict) and "$ref" in schema and depth < 20:
        ref = schema["$ref"].lstrip("#/").split("/")
        node: Any = spec
        for part in ref:
            node = node.get(part, {}) if isinstance(node, dict) else {}
        schema = node
        depth += 1
    return schema if isinstance(schema, dict) else {}


def _match_path(candidate: str, spec_paths: List[str]) -> Optional[str]:
    """Match a normalised frontend path (with `{*}` wildcards) to a spec path.

    Equality on the wildcarded forms only — no regex fallback. A regex would
    let the frontend's `${param}` wildcard match a LITERAL spec segment, and
    dict order decides which comes first: `/v1/data-sources/${id}` (a PUT)
    once "matched" `/api/v1/data-sources/disclosure` (GET-only) because
    `disclosure` sorts before `{data_source_id}`, reporting a phantom
    method violation for a route that serves PUT just fine. A `${param}`
    only ever corresponds to a `{name}` template on the wire.
    """
    for spec_path in spec_paths:
        normalized_spec = spec_path.rstrip("/") or "/"
        spec_wild = re.sub(r"\{[^/{}]+\}", "{*}", normalized_spec)
        if spec_wild == candidate:
            return spec_path
    return None


def _response_schema(op: Dict[str, Any], spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for code in ("200", "201", "202"):
        resp = op.get("responses", {}).get(code)
        if resp:
            break
    else:
        return None
    content = (resp or {}).get("content", {}).get("application/json", {})
    schema = _deref(content.get("schema", {}), spec)
    if schema.get("type") == "array":
        schema = _deref(schema.get("items", {}), spec)
    return schema or None


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def openapi_spec() -> Dict[str, Any]:
    return app.openapi()


@pytest.fixture(scope="module")
def ts_interfaces() -> Dict[str, Dict[str, Any]]:
    assert _TYPES_FILE.exists(), f"{_TYPES_FILE} is missing"
    return parse_ts_interfaces(_TYPES_FILE.read_text(encoding="utf-8"))


def test_frontend_has_typed_calls_to_check():
    """Guard the guard: if extraction ever returns nothing, the contract test
    would pass vacuously — which is exactly the silent-no-op failure mode
    this repo keeps naming. Fail loudly instead."""
    calls = frontend_typed_calls()
    assert len(calls) >= 15, (
        f"only {len(calls)} typed fetchApi/fetchJson calls were extracted "
        "from frontend/src — the extraction regex has drifted from the code "
        "style, and the contract test would pass without checking anything"
    )


def test_every_typed_frontend_call_hits_a_real_endpoint(openapi_spec):
    """Endpoint+method existence against the live schema.

    Complements scripts/check_e2e_api_coverage.mjs (frontend calls vs the
    e2e mock): this leg compares against the server itself, so an endpoint
    the frontend adopts that the backend never served fails here even if the
    mock happens to answer it.
    """
    spec_paths = list(openapi_spec.get("paths", {}).keys())
    missing = []
    for call in frontend_typed_calls():
        matched = _match_path(call["path"], spec_paths)
        if matched is None:
            missing.append(f"{call['method'].upper()} {call['path']}  ({call['file']}) — no such route")
            continue
        methods = {
            key for key in openapi_spec["paths"][matched]
            if key in ("get", "post", "put", "patch", "delete")
        }
        if call["method"] not in methods:
            missing.append(
                f"{call['method'].upper()} {call['path']}  ({call['file']}) — route exists "
                f"but serves {sorted(m.upper() for m in methods)}, not {call['method'].upper()}"
            )
    assert not missing, (
        "frontend calls endpoints the live API does not serve:\n  "
        + "\n  ".join(missing)
        + "\n\nFix the frontend path/method, or the route. Do not paper over "
        "it in the e2e mock: the mock answering a route the app does not "
        "serve is how the broken catalogue URL survived four review rounds."
    )


def _nested_type_name(type_text: str) -> Optional[Tuple[str, bool]]:
    """First declared-type identifier in a TS field type, and whether it is
    an array of it. `Notification[] | null` -> ('Notification', True)."""
    cleaned = type_text.split("|")[0].strip()
    m = re.match(r"^(\w+)\s*(\[\])?", cleaned)
    if not m:
        return None
    name = m.group(1)
    if name in _PRIMITIVE_TYPE_NAMES:
        return None
    return name, bool(m.group(2))


def _collect_field_violations(
    type_name: str,
    schema: Dict[str, Any],
    spec: Dict[str, Any],
    ts_interfaces: Dict[str, Dict[str, Any]],
    visited: set,
    violations: List[str],
    depth: int = 0,
) -> None:
    iface = ts_interfaces.get(type_name)
    if iface is None or iface["open"]:
        return  # unknown or deliberately-open contract: nothing to pin
    props = schema.get("properties")
    if not isinstance(props, dict) or not props:
        return  # Dict[str, Any] / untyped response: reported by the census

    for field in iface["fields"]:
        if field in props:
            if depth >= 4:
                continue
            nested = _nested_type_name(iface["types"].get(field, ""))
            if nested is None:
                continue
            nested_name, is_array = nested
            if nested_name not in ts_interfaces:
                continue
            child = _deref(props[field], spec)
            if is_array and child.get("type") == "array":
                child = _deref(child.get("items", {}), spec)
            pair = (nested_name, id(child))
            if pair in visited:
                continue
            visited.add(pair)
            _collect_field_violations(
                nested_name, child, spec, ts_interfaces, visited, violations, depth + 1
            )
            continue
        if (type_name, field) in ALLOWED_WIRE_EXCEPTIONS:
            continue
        violations.append(
            f"{type_name}.{field} — declared in frontend/src/types/api.ts and "
            f"absent from the wire schema ({sorted(props)[:12]}...)"
        )


def test_frontend_declared_fields_exist_on_the_wire(openapi_spec, ts_interfaces):
    """Every field a bound TS interface declares must exist on the response
    schema of the endpoint that serves it (see module docstring for the
    founding incidents)."""
    spec_paths = list(openapi_spec.get("paths", {}).keys())
    violations: List[str] = []
    untyped: List[str] = []
    visited_top: set = set()

    for call in frontend_typed_calls():
        type_name = call["type"]
        if type_name not in ts_interfaces:
            continue  # `null`, inline generics: no declared shape to pin
        matched = _match_path(call["path"], spec_paths)
        if matched is None:
            continue  # reported by the endpoint test above
        op = openapi_spec["paths"][matched].get(call["method"])
        if not op:
            continue
        schema = _response_schema(op, openapi_spec)
        if schema is None or not schema.get("properties"):
            untyped.append(f"{call['method'].upper()} {call['path']} -> {type_name}")
            continue
        key = (type_name, matched, call["method"])
        if key in visited_top:
            continue
        visited_top.add(key)
        _collect_field_violations(
            type_name, schema, openapi_spec, ts_interfaces, set(), violations
        )

    # The untyped census is printed, not asserted: a Dict[str, Any] endpoint
    # is a known gap (analytics, data quality, system status, network graph),
    # and the pressure to shrink it should be visible, not silent.
    if untyped:
        print(
            "\ncontract census: endpoints whose responses are untyped "
            f"(Dict[str, Any]) on the backend, so field drift there is only "
            f"caught by e2e ({len(set(untyped))}):\n  "
            + "\n  ".join(sorted(set(untyped)))
        )

    assert not violations, (
        "frontend types declare fields the API does not send — the UI would "
        "render undefined for these:\n  " + "\n  ".join(sorted(set(violations)))
        + "\n\nEither the backend schema gained/renamed a field (update "
        "types/api.ts and every reader), or the frontend invented one (delete "
        "it and the UI branch that reads it). If — and only if — another "
        "transport legitimately carries it, add it to ALLOWED_WIRE_EXCEPTIONS "
        "with the reason."
    )
