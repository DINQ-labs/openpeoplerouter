"""Sending one operation to its provider and classifying what came back."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from .catalog import Operation, Param, Provider
from .expr import search as evaluate

OUT_OF_CREDIT = ("insufficient credit", "out of credit", "not enough credit", "quota", "usage limit", "plan limit")


@dataclass
class Outcome:
    """One request: `ok`, `empty` (the provider found nothing) or `failed`."""

    operation: str
    state: str = "failed"
    status: int | None = None
    ms: int = 0
    error: str = ""  # a code from `classify`
    message: str = ""
    data: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    def view(self) -> dict[str, Any]:
        row = {"operation": self.operation, "state": self.state, "ms": self.ms}
        if self.status is not None:
            row["status"] = self.status
        if self.error:
            row["error"] = self.error
            row["message"] = self.message
        row.update(self.extra)
        return row


def classify(status: int, message: str) -> str:
    text = message.lower()
    if status == 402 or (status in (401, 403, 429) and any(w in text for w in OUT_OF_CREDIT)):
        return "out_of_credit"
    if status in (401, 403):
        return "key_rejected"
    if status == 429:
        return "rate_limited"
    if status in (408, 504):
        return "timeout"
    if 400 <= status < 500:
        return "bad_request"
    return "provider_error"


def _message(doc: Any) -> str:
    if isinstance(doc, dict):
        for key in ("message", "error", "detail", "error_message", "msg", "errors", "description"):
            value = doc.get(key)
            if isinstance(value, dict):
                value = value.get("message") or json.dumps(value)[:300]
            if isinstance(value, list) and value:
                value = value[0].get("message") if isinstance(value[0], dict) else value[0]
            if value:
                return str(value)[:300]
    if isinstance(doc, str):
        return doc[:300]
    return ""


def _coerce(param: Param, value: Any) -> Any:
    if param.type == "integer":
        return int(value)
    if param.type == "number":
        return float(value)
    if param.type == "boolean":
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
    if param.type == "array" and not isinstance(value, list):
        return [v.strip() for v in str(value).split(",") if v.strip()]
    return value


def _put(target: Any, dotted: str, value: Any) -> None:
    """Set `a.b`, or `a.0.b` for the first object in list `a`."""
    parts = dotted.split(".")
    for part, following in zip(parts, parts[1:]):
        empty: Any = [] if following.isdigit() else {}
        if part.isdigit():
            index = int(part)
            while len(target) <= index:
                target.append(None)
            if target[index] is None:
                target[index] = empty
            target = target[index]
        else:
            target = target.setdefault(part, empty)
    leaf = parts[-1]
    if leaf.isdigit():
        while len(target) <= int(leaf):
            target.append(None)
        target[int(leaf)] = value
    else:
        target[leaf] = value


def _compact(value: Any) -> Any:
    """Drop the gaps left in a list when only some of its indexed parts were given."""
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_compact(v) for v in value if v is not None and v != {}]
    return value


def _matches(expression: str, doc: Any) -> bool:
    if not expression or not isinstance(doc, (dict, list)):
        return False
    try:
        return bool(evaluate(expression, doc))
    except Exception:  # noqa: BLE001 — an odd error body is just not a "no match"
        return False


def secrets(provider: Provider, env: dict[str, str]) -> dict[str, str]:
    return {name: (env.get(name) or "").strip() for name in provider.key.envs()}


def missing_key(provider: Provider, env: dict[str, str]) -> bool:
    return not provider.key.optional and any(not v for v in secrets(provider, env).values())


def build(provider: Provider, op: Operation, args: dict[str, Any], env: dict[str, str]) -> httpx.Request:
    query: dict[str, Any] = {}
    headers: dict[str, str] = {"Accept": "application/json", "User-Agent": "openpeoplerouter"}
    body: dict[str, Any] = {}
    path = op.path
    for name, value in args.items():
        root = name.split(".")[0]
        param = op.params.get(name) or op.params[root]
        value = _coerce(param, value) if name == root else value
        if param.at == "path":
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        elif param.at == "query":
            # `name[]` params repeat the key per value; others take one comma-separated value
            query[name] = value if name.endswith("[]") or not isinstance(value, list) else ",".join(map(str, value))
            if isinstance(value, bool):
                query[name] = str(value).lower()
        elif param.at == "header":
            headers[name] = str(value)
        else:
            _put(body, name, value)
    if op.body != "whole":  # a whole body is the caller's own object; leave it as given
        body = _compact(body)
    key = provider.key
    secret = (env.get(key.env) or "").strip() if key.env else ""
    if secret:
        if key.body and op.method != "GET":
            body[key.body] = secret
        elif key.query or key.body:
            query[key.query or key.body] = key.prefix + secret
        elif key.basic:
            pair = f"{secret}:" if key.basic == "user" else f":{secret}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            headers[key.header] = key.prefix + secret
        for header, name in key.also:
            headers[header] = (env.get(name) or "").strip()
    url = (op.api or provider.api) + path
    if op.method == "GET" or not body:
        return httpx.Request(op.method, url, params=query, headers=headers)
    if op.body == "form":
        return httpx.Request(op.method, url, params=query, headers=headers, data=body)
    payload = next(iter(body.values()), None) if op.body == "whole" else body
    return httpx.Request(op.method, url, params=query, headers=headers, json=payload)


def check_args(op: Operation, args: dict[str, Any]) -> str:
    unknown = [n for n in args if n not in op.params and n.split(".")[0] not in op.params]
    if unknown:
        return f"unknown params {unknown}; this operation takes {sorted(op.params)}"
    missing = [p.name for p in op.params.values() if p.required and p.default is None and p.name not in args]
    if missing:
        return f"missing required params {missing}"
    for name, value in args.items():
        param = op.params.get(name)
        if param is None:
            continue
        try:
            _coerce(param, value)
        except (TypeError, ValueError):
            return f"param {name} must be {param.type}"
        if param.choices and value not in param.choices:
            return f"param {name} must be one of {list(param.choices)}"
    return ""


async def send(
    client: httpx.AsyncClient, provider: Provider, op: Operation, args: dict[str, Any], env: dict[str, str]
) -> Outcome:
    outcome = Outcome(op.id)
    if missing_key(provider, env):
        outcome.error, outcome.message = "missing_key", f"set {', '.join(provider.key.envs())} to use {provider.title}"
        return outcome
    for p in op.params.values():
        if p.default is not None and p.name not in args:
            args = {**args, p.name: p.default}
    started = time.perf_counter()
    try:
        response = await client.send(build(provider, op, args, env))
    except httpx.TimeoutException:
        outcome.error, outcome.message = "timeout", f"{provider.title} did not answer in time"
    except httpx.HTTPError as exc:
        outcome.error, outcome.message = "network", f"could not reach {provider.title}: {type(exc).__name__}"
    else:
        outcome.status = response.status_code
        try:
            doc = response.json()
        except ValueError:
            doc = response.text[:2000]
        if response.status_code in op.not_found or (response.status_code >= 400 and _matches(op.no_match, doc)):
            outcome.state = "empty"
        elif response.status_code >= 400:
            outcome.message = _message(doc) or f"{provider.title} answered {response.status_code}"
            outcome.error = classify(response.status_code, outcome.message)
        else:
            outcome.state, outcome.data = "ok", doc
    outcome.ms = int((time.perf_counter() - started) * 1000)
    return outcome


def redact(value: Any, hidden: list[str]) -> Any:
    hidden = [h for h in hidden if len(h) >= 4]
    if not hidden:
        return value
    if isinstance(value, dict):
        return {k: redact(v, hidden) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, hidden) for v in value]
    if isinstance(value, str):
        for h in hidden:
            value = value.replace(h, "[redacted]")
    return value
