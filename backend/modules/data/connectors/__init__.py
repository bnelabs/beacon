"""Registry of the non-bank / market-infrastructure connectors.

Each connector is imported lazily, so a single unavailable module cannot stop the
others from being discovered, and importing this package stays cheap.

Usage::

    from backend.modules.data.connectors import build_connector, available_connectors

    for name, description in available_connectors().items():
        ...

    connector = build_connector("sec_n_mfp")
    report = connector.load(store, FetchRequest(start="2024-01-01"))
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Mapping, Type

from .base import (
    DEFAULT_USER_AGENT,
    ConnectorReport,
    ConnectorSpec,
    DataConnector,
    FetchRequest,
    HttpClient,
    as_float,
    frame_to_observations,
    require,
    validate_observation_frame,
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "ConnectorReport",
    "ConnectorSpec",
    "DataConnector",
    "FetchRequest",
    "HttpClient",
    "as_float",
    "frame_to_observations",
    "require",
    "validate_observation_frame",
    "CONNECTORS",
    "available_connectors",
    "build_connector",
    "describe_connectors",
]

#: Registry name -> ``(module, class name)``. Imported on demand by
#: :func:`build_connector`; see each module for the source's terms of use.
CONNECTORS: Mapping[str, tuple] = {
    "sec_n_mfp": (".sec_n_mfp", "SecNMfpConnector"),
    "bis_credit": (".bis_credit", "BisCreditConnector"),
    "ecb_ccp": (".ecb_ccp", "EcbCcpConnector"),
    "payments": (".payments", "PaymentsConnector"),
    "sec_form_pf": (".sec_form_pf", "SecFormPfConnector"),
}


def build_connector(name: str, **kwargs: Any) -> DataConnector:
    """Instantiate the connector registered under ``name``.

    Raises:
        ValueError: ``name`` is not registered. The message lists what is.
    """
    try:
        module_name, class_name = CONNECTORS[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown connector {name!r}; available: {sorted(CONNECTORS)}"
        ) from exc
    module = import_module(module_name, package=__name__)
    factory: Type[DataConnector] = getattr(module, class_name)
    return factory(**kwargs)


def available_connectors() -> Dict[str, str]:
    """Registry names mapped to their one-line description."""
    described: Dict[str, str] = {}
    for name in CONNECTORS:
        try:
            described[name] = build_connector(name).spec.description
        except Exception as exc:  # noqa: BLE001 - discovery must not raise
            described[name] = f"<unavailable: {type(exc).__name__}: {exc}>"
    return described


def describe_connectors() -> Dict[str, Dict[str, Any]]:
    """Full :class:`ConnectorSpec` for every registered connector."""
    payload: Dict[str, Dict[str, Any]] = {}
    for name in CONNECTORS:
        try:
            payload[name] = build_connector(name).spec.to_dict()
        except Exception as exc:  # noqa: BLE001
            payload[name] = {"name": name, "error": f"{type(exc).__name__}: {exc}"}
    return payload
