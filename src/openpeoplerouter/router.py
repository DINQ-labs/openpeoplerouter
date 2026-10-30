"""Answering a job from the providers this installation has keys for.

Candidates are the operations whose route accepts the inputs given. They are tried
in order — the providers named in OPENPEOPLEROUTER_ORDER first, then by the route's
priority, then cheapest first, unknown prices last — until one answers (one-record
jobs) or enough rows are collected (list jobs, merged and de-duplicated).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .call import Outcome, check_args, missing_key, redact, send
from .catalog import Catalog, Operation, Route
from .expr import search as evaluate
from .jobs import JOBS, derive

MAX_TRIES = 3


class Router:
    def __init__(self, catalog: Catalog, env: dict[str, str], transport: httpx.AsyncBaseTransport | None = None):
        self.catalog = catalog
        self.env = env
        self.transport = transport
        self.allowed = _names(env.get("OPENPEOPLEROUTER_PROVIDERS"))
        self.order = _names(env.get("OPENPEOPLEROUTER_ORDER"))

    def configured(self, provider: str) -> bool:
        if self.allowed and provider not in self.allowed:
            return False
        p = self.catalog.providers.get(provider)
        return p is not None and not missing_key(p, self.env)

    def _hidden(self) -> list[str]:
        return [self.env[e] for p in self.catalog.providers.values() for e in p.key.envs() if self.env.get(e)]

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=60.0, follow_redirects=True)

    def candidates(self, job: str, given: dict[str, Any], only: list[str] | None = None):
        rows = []
        for op, route in self.catalog.routes(job):
            if only and op.provider not in only:
                continue
            if not self.configured(op.provider) or route.usable(given) is None:
                continue
            provider = self.catalog.providers[op.provider]
            usd = provider.usd(op)
            rank = self.order.index(op.provider) if op.provider in self.order else len(self.order)
            rows.append(((rank, -route.priority, usd is None, usd or 0.0, op.id), op, route))
        return [(op, route) for _, op, route in sorted(rows, key=lambda r: r[0])]

    async def run(self, job_name: str, given: dict[str, Any], providers: list[str] | None = None,
                  raw: bool = False, max_tries: int = MAX_TRIES) -> dict[str, Any]:
        job = JOBS[job_name]
        given = derive(job_name, {**job.defaults, **given})
        limit = int(given.get("limit") or 0)
        plan = self.candidates(job_name, given, providers)
        if not plan:
            return redact({"job": job_name, "state": "no_provider", "message": self._why_none(job_name, given, providers)}, self._hidden())
        tried: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        record: dict[str, Any] | None = None
        async with self._client() as client:
            for op, route in plan[:max_tries]:
                outcome = await self._attempt(client, op, route, given, limit)
                found = self._read(route, outcome, job.fields, raw) if outcome.state == "ok" else []
                if outcome.state == "ok" and not found:
                    outcome.state = "empty"
                outcome.extra["provider"] = op.provider
                if found:
                    outcome.extra["rows" if job.many else "found"] = len(found) if job.many else True
                tried.append(outcome.view())
                if not found:
                    continue
                if not job.many:
                    record = found[0]
                    break
                rows = _merge(rows, found)
                if limit and len(rows) >= limit:
                    break
        result: dict[str, Any] = {"job": job_name, "tried": tried}
        if job.many:
            result["state"] = "found" if rows else "empty"
            result["rows"] = rows[:limit] if limit else rows
        else:
            result["state"] = "found" if record else "empty"
            result["record"] = record
        if not rows and not record and tried and all(t["state"] == "failed" for t in tried):
            result["state"] = "failed"
        return redact(result, self._hidden())

    async def _attempt(self, client, op: Operation, route: Route, given: dict[str, Any], limit: int) -> Outcome:
        args = dict(route.fixed)  # constants first, so inputs can extend a fixed query prefix
        for name, entry in route.send.items():
            value = given.get(name)
            if value in (None, "", []):
                continue
            param = entry
            if isinstance(entry, dict):  # the value goes inside a fixed structure
                param, value = entry["to"], _fill(entry.get("as", "$"), value)
                if isinstance(args.get(param), str) and isinstance(value, str):
                    value = f"{args[param]} {value}"  # several inputs make one query string
                args[param] = value
                continue
            spec = op.params.get(param)
            if spec is None and param.endswith("[]"):  # `a.b[]`: a list where the job has one value
                param, spec = param[:-2], None
                value = _listed(value)
            elif spec is not None and spec.type == "array":
                value = _listed(value)
            if isinstance(args.get(param), str) and isinstance(value, str):
                value = f"{args[param]} {value}"
            args[param] = value
        if route.limit and limit:
            args[route.limit] = limit
        provider = self.catalog.providers[op.provider]
        outcome = await send(client, provider, op, args, self.env)
        if route.poll is None or outcome.state != "ok":
            return outcome
        return await self._poll(client, provider, route.poll, outcome)

    async def _poll(self, client, provider, poll, first: Outcome) -> Outcome:
        """Ask for the answer until it is ready, the first reply being only a receipt."""
        target = provider.operations[poll.operation]
        if poll.when:
            try:
                if not evaluate(poll.when, first.data):
                    return first  # the first reply already holds the answer
            except Exception:  # noqa: BLE001
                return first
        try:
            args = {param: evaluate(expr, first.data) for param, expr in poll.send.items()}
        except Exception:  # noqa: BLE001
            args = {}
        if any(v in (None, "") for v in args.values()):
            first.state, first.error, first.message = "failed", "provider_error", "no request id in the reply"
            return first
        waited, outcome = 0.0, first
        while waited <= poll.within:
            await asyncio.sleep(poll.every if waited else min(poll.every, 1.0))
            waited += poll.every
            outcome = await send(client, provider, target, args, self.env)
            if outcome.state != "ok":
                break
            try:
                if evaluate(poll.until, outcome.data):
                    break
            except Exception:  # noqa: BLE001
                break
        else:
            outcome.state, outcome.error, outcome.message = "failed", "timeout", f"no answer within {poll.within:.0f}s"
        outcome.ms += first.ms
        outcome.operation = first.operation
        return outcome

    def _read(self, route: Route, outcome: Outcome, wanted: tuple[str, ...], raw: bool) -> list[dict[str, Any]]:
        try:
            found = evaluate(route.result, outcome.data)
        except Exception:  # noqa: BLE001 — a reply that does not fit reads as nothing
            return []
        items = found if isinstance(found, list) else [found]
        out = []
        for item in items:
            if item in (None, {}, []):
                continue
            row = {"provider": outcome.operation.split(".")[0]}
            for name in wanted:
                expr = route.fields.get(name)
                if expr:
                    value = evaluate(expr, item)
                    if value not in (None, "", [], {}):
                        row[name] = value
            if len(row) == 1:
                continue
            if raw:
                row["raw"] = item
            out.append(row)
        return out

    def _why_none(self, job: str, given: dict[str, Any], only: list[str] | None) -> str:
        routes = [(op, r) for op, r in self.catalog.routes(job) if not only or op.provider in only]
        fitting = [op.provider for op, r in routes if r.usable(given) is not None]
        if not fitting:
            needs = sorted({" + ".join(o) for _, r in routes for o in r.needs})
            return f"no provider answers {job} from these inputs; options: {needs[:12]}"
        keys = sorted({e for p in dict.fromkeys(fitting) for e in self.catalog.providers[p].key.envs()})
        return f"providers that could answer are not configured; set one of {keys[:15]}"

    async def call(self, operation_id: str, args: dict[str, Any]) -> dict[str, Any]:
        op = self.catalog.operations.get(operation_id)
        if op is None:
            return {"state": "failed", "error": "unknown_operation", "message": "use search_operations to find one"}
        if self.allowed and op.provider not in self.allowed:
            return {"state": "failed", "error": "provider_disabled", "message": "not in OPENPEOPLEROUTER_PROVIDERS"}
        problem = check_args(op, args)
        if problem:
            return {"state": "failed", "error": "bad_request", "message": problem}
        async with self._client() as client:
            outcome = await send(client, self.catalog.providers[op.provider], op, args, self.env)
        return redact({**outcome.view(), "data": outcome.data}, self._hidden())


def _fill(template: Any, value: Any) -> Any:
    if template == "$":
        return value
    if isinstance(template, str) and "$" in template:
        text = str(value)
        return template.replace("$", f'"{text}"' if " " in text and '"$"' not in template else text)
    if isinstance(template, dict):
        return {k: _fill(v, value) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, value) for v in template]
    return template


def _listed(value: Any) -> list:
    return value if isinstance(value, list) else [v.strip() for v in str(value).split(",") if v.strip()]


def _names(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _identity(row: dict[str, Any]) -> list[str]:
    keys = []
    for name in ("linkedin_url", "url", "email", "domain", "website"):
        if row.get(name):
            keys.append(f"{name}:{str(row[name]).lower().rstrip('/').split('://')[-1].removeprefix('www.')}")
    if row.get("name"):
        keys.append("name:" + json.dumps([str(row["name"]).lower(), str(row.get("company") or row.get("domain") or "").lower()]))
    return keys


def _merge(rows: list[dict[str, Any]], more: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {key: i for i, row in enumerate(rows) for key in _identity(row)}
    for row in more:
        match = next((seen[k] for k in _identity(row) if k in seen), None)
        if match is None:
            rows.append(row)
            match = len(rows) - 1
        else:
            existing = rows[match]
            for k, v in row.items():
                existing.setdefault(k, v)
            others = sorted({*existing.get("also_from", []), row["provider"]} - {existing["provider"]})
            if others:
                existing["also_from"] = others
        for key in _identity(rows[match]):
            seen.setdefault(key, match)
    return rows
