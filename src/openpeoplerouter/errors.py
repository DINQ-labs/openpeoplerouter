"""Errors, one vocabulary.

`classify_error` turns whatever a vendor call raised into a code; `error_view` renders a
code as the error block every answer carries, with the hint an agent needs to decide
whether to try elsewhere.
"""

from __future__ import annotations

from typing import Any

import httpx

ERROR_CODES: dict[str, tuple[bool, str]] = {
    "bad_input": (False, "The input is not something this vendor accepts. Fix the input; do not retry it elsewhere as-is."),
    "not_found": (False, "The entity does not exist at that address. Web-search the current URL before retrying."),
    "missing_credential": (True, "This server has no credential for the vendor; it is unavailable here. Another vendor may still answer."),
    "credential_rejected": (True, "The vendor rejected this server's credential. Not your input; another vendor may still answer."),
    "rate_limited": (True, "The vendor is rate limiting this server. Try another vendor now, or this one later."),
    "timeout": (True, "The vendor did not answer in time. Try once more, then another vendor."),
    "provider_error": (True, "The vendor failed on its side. Try another vendor."),
    "internal_error": (True, "Unexpected failure inside this server. Report it and use another vendor."),
    "vendor_exhausted": (True, "This server's account with that vendor has run out of credits or hit its plan limit. Another provider may still answer; check its billing policy."),
}


def classify_error(exc: BaseException) -> tuple[str, int | None, str]:
    """Map any exception a vendor call raises to (code, http_status, message)."""
    status = getattr(exc, "status", None)
    message = getattr(exc, "message", None) or str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", None, message
    if isinstance(exc, httpx.HTTPError):
        return "provider_error", None, message
    if isinstance(status, int):
        if status == 400 and message.lower().startswith("missing "):
            return "missing_credential", status, message
        if status == 400:
            return "bad_input", status, message
        if status in (401, 403):
            return "credential_rejected", status, message
        if status == 404:
            return "not_found", status, message
        if status == 429:
            return "rate_limited", status, message
        if status in (408, 504):
            return "timeout", status, message
        return "provider_error", status, message
    return "internal_error", None, message


def error_view(code: str, message: str, *, status: int | None = None) -> dict[str, Any]:
    retry_elsewhere, hint = ERROR_CODES.get(code, ERROR_CODES["internal_error"])
    out = {"code": code, "message": message[:300], "hint": hint, "retry_elsewhere": retry_elsewhere}
    if status is not None:
        out["status"] = status
    return out
