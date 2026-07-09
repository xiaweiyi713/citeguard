"""Registrar-agnostic DOI existence probe backed by the global Handle registry.

Open scholarly sources (OpenAlex/Crossref) miss papers whose DOIs are
registered with other agencies, such as China DOI (ISTIC). The doi.org handle
API resolves every registered DOI regardless of agency, so it can confirm that
a DOI exists even when no open source carries its metadata. It never returns
bibliographic metadata, so it strengthens or weakens confidence in a
`not_found` verdict without ever proving support or fabrication.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from .http import HTTPClient
from .utils import normalize_doi

REGISTERED = "registered"
NOT_REGISTERED = "not_registered"
UNAVAILABLE = "unavailable"

_INTERPRETATIONS = {
    REGISTERED: "doi_registered_metadata_may_be_closed_access_not_full_verification",
    NOT_REGISTERED: "doi_not_in_global_handle_registry_lowers_confidence_not_fabrication_proof",
    UNAVAILABLE: "doi_registry_unreachable_no_conclusion",
}


class DoiRegistryProbe:
    """Check whether a DOI exists in the global Handle System (doi.org)."""

    name = "doi_org"
    BASE_URL = "https://doi.org/api/handles"

    def __init__(self, http_client: Optional[HTTPClient] = None) -> None:
        self.http_client = http_client or HTTPClient()

    def check(self, doi: str) -> Dict[str, Any]:
        normalized = normalize_doi(doi)
        if not normalized:
            return self._result(UNAVAILABLE, doi="", detail="missing_doi")

        payload = self.http_client.get_json(
            f"{self.BASE_URL}/{quote(normalized, safe='/')}",
            params={"type": "URL"},
        )
        response_code = payload.get("responseCode") if isinstance(payload, dict) else None
        if response_code == 1:
            resolution_url = ""
            for value in payload.get("values", []) or []:
                if isinstance(value, dict) and value.get("type") == "URL":
                    data = value.get("data")
                    if isinstance(data, dict) and data.get("value"):
                        resolution_url = str(data["value"])
                        break
            return self._result(REGISTERED, doi=normalized, resolution_url=resolution_url)
        if response_code == 100:
            return self._result(NOT_REGISTERED, doi=normalized)
        # The handle API answers HTTP 404 (responseCode 100 in the body) for
        # unknown handles; our HTTP client drops non-retryable error bodies,
        # so treat a definite 404 as "not registered" rather than an outage.
        if getattr(self.http_client, "last_status_code", None) == 404:
            return self._result(NOT_REGISTERED, doi=normalized)
        detail = self.http_client.last_error or "invalid_response"
        return self._result(UNAVAILABLE, doi=normalized, detail=detail)

    def _result(self, status: str, doi: str, resolution_url: str = "", detail: str = "") -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "checked": status != UNAVAILABLE,
            "registry": self.name,
            "doi": doi,
            "status": status,
            "registered": True if status == REGISTERED else False if status == NOT_REGISTERED else None,
            "interpretation": _INTERPRETATIONS[status],
        }
        if resolution_url:
            result["resolution_url"] = resolution_url
        if detail:
            result["detail"] = detail
        return result
