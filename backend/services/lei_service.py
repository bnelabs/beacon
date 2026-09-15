"""GLEIF LEI resolution: the join key across FDIC, EBA and BIS data.

Round-eight adoption. Institution-level sources identify entities differently
(RSSD ids at the FDIC, EBA reporting codes, BIS country-sector aggregates);
the Legal Entity Identifier is the only public, keyless vocabulary that joins
them, and GLEIF publishes it (with direct/ultimate parent relationships) over
a free JSON:API.

This service resolves and caches LEI records; it does not guess matches. A
fuzzy name search returns candidates with their LEIs and the caller decides.
Without a confident match, callers keep entities separate -- silently joining
two different banks because their names look alike would corrupt every
network aggregate downstream.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

BASE = "https://api.gleif.org/api/v1"
_CACHE_TTL_SECONDS = 3600


class LEIService:
    """Resolve LEI records and parent relationships from GLEIF (keyless)."""

    def __init__(self, timeout: int = 20, cache_ttl: int = _CACHE_TTL_SECONDS) -> None:
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, tuple] = {}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        response = requests.get(f"{BASE}{path}", params=params or {}, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def resolve(self, lei: str) -> Optional[Dict[str, Any]]:
        """The record for one LEI, or ``None`` when GLEIF does not know it."""
        key = f"lei:{lei}"
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < self.cache_ttl:
            return cached[1]
        payload = self._get(f"/lei-records/{lei}")
        data = payload.get("data")
        record = self._parse(data[0] if isinstance(data, list) and data else data)
        self._cache[key] = (time.time(), record)
        return record

    def search(self, name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Candidate records for a legal name; the caller decides on a match."""
        payload = self._get("/lei-records", params={"search": name, "page[size]": limit})
        data = payload.get("data") or []
        return [record for record in (self._parse(item) for item in data) if record]

    def parents(self, lei: str) -> Dict[str, Optional[str]]:
        """Direct and ultimate parent LEIs, ``None`` when non-consolidating."""
        payload = self._get(f"/lei-records/{lei}/relationships/parents")
        data = payload.get("data") or []
        out: Dict[str, Optional[str]] = {"direct": None, "ultimate": None}
        for relation in data:
            kind = str(relation.get("relationships", {}).get("type", "")).lower()
            target = ((relation.get("relationships") or {}).get("parent") or {}).get("data") or {}
            kind_key = "ultimate" if "ultimate" in kind else "direct"
            if target.get("id"):
                out[kind_key] = str(target["id"])
        return out

    @staticmethod
    def _parse(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict):
            return None
        attributes = item.get("attributes") or {}
        lei = attributes.get("lei") or item.get("id")
        if not lei:
            return None
        entity = attributes.get("entity") or {}
        return {
            "lei": str(lei),
            "legal_name": (entity.get("legalName") or {}).get("name") if isinstance(entity.get("legalName"), dict) else entity.get("legalName"),
            "status": attributes.get("status"),
            "jurisdiction": entity.get("jurisdiction"),
        }
