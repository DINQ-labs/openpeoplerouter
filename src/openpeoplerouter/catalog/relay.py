"""Running one endpoint.

Two kinds of endpoint execute here. Most are plain HTTP described entirely in the
vendor's YAML: the relay builds the URL, injects the credential, sends the request
and hands the body to the adapter. A few are `native:` — our own composite channels
(a repository's contributors, a company's people) that take several calls and some
judgement, so they stay in Python and are registered by name.

Either way the caller sees the same thing: a contract-shaped answer, an outcome of
hit / miss / error, and never an exception.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from openpeoplerouter.catalog.models import Endpoint, Vendor
from openpeoplerouter.catalog.plan import Candidate
from openpeoplerouter.catalog.store import Catalog
from openpeoplerouter.errors import classify_error, error_view

logger = logging.getLogger("openpeoplerouter.catalog.relay")

DEFAULT_TIMEOUT = 60.0


@dataclass
class Attempt:
    """One vendor, one call, what came of it."""

    endpoint: str
    vendor: str
    outcome: str = "error"  # hit | miss | error | skipped
    status: int | None = None
    duration_ms: int = 0
    error: dict[str, Any] | None = None
    note: str = ""
    ignored: tuple[str, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)

    def view(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "endpoint": self.endpoint,
            "vendor": self.vendor,
            "outcome": self.outcome,
            "duration_ms": self.duration_ms,
        }
        if self.status is not None:
            row["status"] = self.status
        if self.error:
            row["error"] = self.error
        if self.note:
            row["note"] = self.note
        if self.ignored:
            row["ignored_filters"] = list(self.ignored)
        row.update(self.extras)
        return row


_EXHAUSTED = ("insufficient credit", "out of credit", "quota", "plan limit", "usage limit", "not enough credit")


def code_for_status(status: int, message: str = "") -> str:
    """A vendor that has run out is not a vendor that rejected us: nothing is wrong
    with the credential, this server just needs to top up. Both are free to the caller."""
    text = (message or "").lower()
    if status == 402 or (status in (401, 403) and any(word in text for word in _EXHAUSTED)):
        return "vendor_exhausted"
    if status in (401, 403):
        return "credential_rejected"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status in (408, 504):
        return "timeout"
    if 400 <= status < 500:
        return "bad_input"
    return "provider_error"


class Relay:
    """Executes catalog endpoints over HTTP."""

    def __init__(
        self,
        catalog: Catalog,
        *,
        credentials: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.catalog = catalog
        self.credentials = credentials  # None = read the process environment
        self._timeout = timeout
        self._transport = transport

    # ---- credentials ----------------------------------------------------------------------------

    def secret(self, vendor: Vendor) -> str:
        if vendor.auth.kind == "none" or not vendor.auth.credential:
            return ""
        if self.credentials is not None:
            return (self.credentials.get(vendor.auth.credential) or "").strip()
        import os

        return (os.getenv(vendor.auth.credential) or "").strip()

    # ---- one call -------------------------------------------------------------------------------

    async def run(self, candidate: Candidate, identity: dict[str, Any]) -> tuple[Any, Attempt]:
        endpoint, adapter = candidate.endpoint, candidate.adapter
        attempt = Attempt(
            endpoint=endpoint.id, vendor=endpoint.vendor, ignored=candidate.ignored
        )
        vendor = self.catalog.vendors.get(endpoint.vendor)
        if vendor is None:
            attempt.error = error_view("internal_error", f"vendor {endpoint.vendor} is not in the catalog")
            return None, attempt

        query, body, path_params = adapter.to_upstream(identity, candidate.variant)
        started = time.perf_counter()
        try:
            status, doc = await self._run_http(vendor, endpoint, query, body, path_params, adapter.body_array)
            attempt.status = status
            if status == endpoint.miss_status:
                # The vendor says "nobody matched" with a status code. That is an
                # answer, and a free one — not an error to retry.
                attempt.duration_ms = int((time.perf_counter() - started) * 1000)
                attempt.outcome = "miss"
                attempt.note = endpoint.miss_note or f"{vendor.name} found nobody"
                return None, attempt
            if status >= 400:
                attempt.duration_ms = int((time.perf_counter() - started) * 1000)
                message = _message_from(doc) or f"{vendor.name} answered {status}"
                code = code_for_status(status, message)
                attempt.error = error_view(code, message, status=status)
                attempt.extras["body"] = _small(doc)
                return None, attempt
        except Exception as exc:  # noqa: BLE001 — every vendor failure becomes a classified attempt
            code, status, message = classify_error(exc)
            attempt.duration_ms = int((time.perf_counter() - started) * 1000)
            attempt.status = status
            attempt.error = error_view(code, message, status=status)
            return None, attempt

        attempt.duration_ms = int((time.perf_counter() - started) * 1000)
        if adapter.is_miss(doc):
            attempt.outcome = "miss"
            attempt.note = endpoint.miss_note
            return doc, attempt
        attempt.outcome = "hit"
        return doc, attempt

    async def call(self, endpoint: Endpoint, args: dict[str, Any]) -> tuple[Any, Attempt]:
        """Call one endpoint directly, with the vendor's own parameter names.

        This is the door to everything in the catalog that no contract covers: the
        agent found the endpoint by words, read its input spec, and passes those inputs
        as they are. The response comes back whole; nothing is mapped."""
        attempt = Attempt(endpoint=endpoint.id, vendor=endpoint.vendor)
        vendor = self.catalog.vendors.get(endpoint.vendor)
        if vendor is None:
            attempt.error = error_view("bad_input", f"{endpoint.id} cannot be called directly")
            return None, attempt
        spec = endpoint.inputs or {}
        query: dict[str, str] = {}
        body: dict[str, Any] = {}
        path_params: dict[str, str] = {}
        unknown = []
        for name, value in (args or {}).items():
            if value in (None, ""):
                continue
            if name in (spec.get("queryParams") or {}):
                query[name] = str(value)
            elif name in (spec.get("body") or {}):
                body[name] = value
            elif name in (spec.get("pathParams") or {}):
                path_params[name] = str(value)
            else:
                unknown.append(name)
        if unknown:
            known = sorted({*spec.get("queryParams", {}), *spec.get("body", {}), *spec.get("pathParams", {})})
            attempt.error = error_view("bad_input", f"{endpoint.id} does not take {unknown}; it takes {known}", status=400)
            return None, attempt
        required = [
            name for where in ("queryParams", "body", "pathParams")
            for name, meta in (spec.get(where) or {}).items()
            if isinstance(meta, dict) and meta.get("required") and name not in {**query, **body, **path_params}
        ]
        if required:
            attempt.error = error_view("bad_input", f"{endpoint.id} needs {required}", status=400)
            return None, attempt
        started = time.perf_counter()
        try:
            status, doc = await self._run_http(vendor, endpoint, query, body, path_params, False)
            attempt.status = status
            attempt.duration_ms = int((time.perf_counter() - started) * 1000)
            if status == endpoint.miss_status:
                attempt.outcome = "miss"
                attempt.note = endpoint.miss_note or f"{vendor.name} found nothing"
                return None, attempt
            if status >= 400:
                message = _message_from(doc) or f"{vendor.name} answered {status}"
                attempt.error = error_view(code_for_status(status, message), message, status=status)
                return None, attempt
        except Exception as exc:  # noqa: BLE001 — every vendor failure becomes a classified attempt
            code, status, message = classify_error(exc)
            attempt.duration_ms = int((time.perf_counter() - started) * 1000)
            attempt.status = status
            attempt.error = error_view(code, message, status=status)
            return None, attempt
        attempt.outcome = "miss" if doc in (None, "", [], {}) else "hit"
        return doc, attempt

    async def _run_http(
        self,
        vendor: Vendor,
        endpoint: Endpoint,
        query: dict[str, str],
        body: dict[str, Any],
        path_params: dict[str, str],
        body_array: bool,
    ) -> tuple[int, Any]:
        url = _render(vendor.base_url, endpoint.path, path_params)
        headers = {"Accept": "application/json"}
        params = dict(query)
        secret = self.secret(vendor)
        if vendor.auth.kind == "header" and secret:
            headers[vendor.auth.name] = vendor.auth.format.format(secret=secret)
        elif vendor.auth.kind == "query" and secret:
            params[vendor.auth.name] = vendor.auth.format.format(secret=secret)
        for name, value in vendor.auth.extra_headers:
            # `${NAME}` names a second credential — Tomba wants a key and a secret —
            # so the value comes from the environment, never from the catalog.
            headers[name] = _fill_credentials(value, self.credentials)

        payload: Any = None
        if body:
            payload = [body] if body_array else body
            headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.request(endpoint.method, url, params=params, json=payload, headers=headers)
        try:
            doc = response.json()
        except ValueError:
            doc = {"_text": (response.text or "")[:500]}
        return response.status_code, doc


def _render(base_url: str, path: str, path_params: dict[str, str]) -> str:
    rendered = path or "/"
    for name, value in path_params.items():
        rendered = rendered.replace(f"{{{name}}}", quote(str(value), safe=""))
    return base_url.rstrip("/") + "/" + rendered.lstrip("/")


def _small(doc: Any) -> Any:
    """A vendor error body, trimmed to what a person needs to see in the console."""
    from openpeoplerouter.catalog.capture import prune

    if isinstance(doc, (dict, list)):
        return prune(doc)
    return str(doc)[:1000] if doc is not None else None


def _message_from(doc: Any) -> str:
    if isinstance(doc, dict):
        for key in ("error", "message", "detail", "error_message", "_text"):
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
            if isinstance(value, dict):
                nested = value.get("message") or value.get("detail")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()[:300]
    return ""


_CREDENTIAL_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _fill_credentials(value: str, credentials: dict[str, str]) -> str:
    return _CREDENTIAL_REF.sub(lambda m: credentials.get(m.group(1), ""), value)
