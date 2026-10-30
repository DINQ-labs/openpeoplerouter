"""Provider files: loading, checking and searching them.

One YAML file per provider under `providers/`. The format is documented in
docs/provider-format.md; `openpeoplerouter check` runs `Catalog.problems`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import Any

from .expr import compile as compile_expression
from .expr import unknown_function
import yaml

from .jobs import AUDIENCES, JOBS

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
LOCATIONS = {"query", "body", "path", "header", "form"}
TYPES = {"string", "integer", "number", "boolean", "array", "object"}
PER = {"call", "success", "result"}
DERIVED = {"first_name", "last_name", "full_name", "linkedin_handle", "handle", "platform"}
CARRIED_BY = {  # an input is sent when any of these, derived from it, is sent
    "linkedin_url": {"linkedin_handle"},
    "full_name": {"first_name", "last_name"},
    "url": {"handle"},
}


@dataclass(frozen=True)
class Key:
    """Where the provider's secret goes. `env` names the variable that holds it."""

    env: str = ""
    header: str = ""
    prefix: str = ""
    query: str = ""
    basic: str = ""  # "user": the key is the username; "password": the key is the password
    body: str = ""  # a JSON body field that carries the key (a query param on GET)
    also: tuple[tuple[str, str], ...] = ()  # second secrets: (header, env)
    optional: bool = False  # the API answers without a key too, with lower limits

    @property
    def needed(self) -> bool:
        return bool(self.env)

    def envs(self) -> list[str]:
        return [e for e in (self.env, *(env for _, env in self.also)) if e]


@dataclass(frozen=True)
class Param:
    name: str
    at: str = "query"
    type: str = "string"
    required: bool = False
    about: str = ""
    default: Any = None
    choices: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Route:
    """How one operation answers one job."""

    job: str
    needs: tuple[tuple[str, ...], ...]  # any one of these sets of inputs is enough
    send: dict[str, Any]  # job input -> operation param, or {to: param, as: template with "$" for the value}
    fixed: dict[str, Any]  # param -> constant
    result: str  # JMESPath to the record, or to the list for a job with many rows
    fields: dict[str, str]  # answer field -> JMESPath within the record
    platform: str = ""  # read_profile only: the platform this operation reads
    limit: str = ""  # param that caps how many rows come back
    poll: "Poll | None" = None  # the provider answers later: ask this operation until it is done
    audience: tuple[str, ...] = ("professionals",)  # find_people only: who this source covers; "any" for all
    priority: int = 0  # higher goes first among routes the caller has not ordered (before price)

    def usable(self, given: dict[str, Any]) -> tuple[str, ...] | None:
        if self.platform and given.get("platform") != self.platform:
            return None
        wanted = given.get("audience")
        if self.job == "find_people" and wanted and "any" not in self.audience and wanted not in self.audience:
            return None
        for option in self.needs:
            if all(given.get(name) not in (None, "", []) for name in option):
                return option
        return None


@dataclass(frozen=True)
class Poll:
    operation: str  # another operation of the same provider
    send: dict[str, str]  # its param -> JMESPath into the first response
    until: str  # JMESPath that is true once the answer is complete
    every: float = 2.0
    within: float = 60.0
    when: str = ""  # JMESPath on the first reply: poll only when true (empty: always)


@dataclass(frozen=True)
class Price:
    usd: float | None = None
    credits: float | None = None
    per: str = "call"
    note: str = ""

    @property
    def free(self) -> bool:
        return self.usd == 0 or self.credits == 0


@dataclass(frozen=True)
class Operation:
    provider: str
    name: str
    title: str
    method: str
    path: str
    params: dict[str, Param]
    about: str = ""
    docs: str = ""
    price: Price = field(default_factory=Price)
    not_found: tuple[int, ...] = ()  # statuses that mean "no match", not failure
    no_match: str = ""  # JMESPath on an error reply that means "no match", e.g. error_code == 'NO_MATCH'
    routes: tuple[Route, ...] = ()
    body: str = "json"  # json | form | whole (the JSON body is the value of its one body param)
    api: str = ""  # when this one operation lives on another host of the same provider

    @property
    def id(self) -> str:
        return f"{self.provider}.{self.name}"

    def view(self, full: bool = False) -> dict[str, Any]:
        row: dict[str, Any] = {"id": self.id, "title": self.title, "request": f"{self.method} {self.path}"}
        if self.routes:
            row["jobs"] = [r.job for r in self.routes]
        price = {k: v for k, v in (("usd", self.price.usd), ("credits", self.price.credits)) if v is not None}
        if price:
            row["price"] = {**price, "per": self.price.per, **({"note": self.price.note} if self.price.note else {})}
        if full:
            row["about"] = self.about
            row["docs"] = self.docs
            row["params"] = {
                p.name: {k: v for k, v in (("in", p.at), ("type", p.type), ("required", p.required or None),
                                           ("about", p.about or None), ("default", p.default),
                                           ("choices", list(p.choices) or None)) if v is not None}
                for p in self.params.values()
            }
        return row


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    api: str
    key: Key
    site: str = ""
    docs: str = ""
    pricing: str = ""
    credit_usd: float | None = None  # what one provider credit costs on its entry plan
    about: str = ""
    operations: dict[str, Operation] = field(default_factory=dict)

    def usd(self, op: Operation) -> float | None:
        if op.price.usd is not None:
            return op.price.usd
        if op.price.credits is not None and self.credit_usd is not None:
            return op.price.credits * self.credit_usd
        return 0.0 if op.price.free else None


def _tuple(value: Any) -> tuple:
    if value is None:
        return ()
    return tuple(value) if isinstance(value, (list, tuple)) else (value,)


def _param(name: str, raw: Any) -> Param:
    raw = raw or {}
    return Param(
        name=name,
        at=str(raw.get("in", "query")),
        type=str(raw.get("type", "string")),
        required=bool(raw.get("required", False)),
        about=str(raw.get("about", "")),
        default=raw.get("default"),
        choices=_tuple(raw.get("choices")),
    )


def _route(job: str, raw: dict[str, Any]) -> Route:
    needs = raw.get("needs") or []
    if needs and isinstance(needs[0], str):
        needs = [needs]
    return Route(
        job=job,
        needs=tuple(tuple(option) for option in needs),
        send=dict(raw.get("send") or {}),
        fixed=dict(raw.get("fixed") or {}),
        result=str(raw.get("result") or "@"),
        fields=dict(raw.get("fields") or {}),
        platform=str(raw.get("platform") or ""),
        limit=str(raw.get("limit") or ""),
        poll=_poll(raw.get("poll")),
        audience=tuple(_tuple(raw.get("audience")) or ("professionals",)),
        priority=int(raw.get("priority") or 0),
    )


def _poll(raw: Any) -> Poll | None:
    if not raw:
        return None
    return Poll(
        operation=str(raw.get("operation", "")),
        send=dict(raw.get("send") or {}),
        until=str(raw.get("until") or "@"),
        every=float(raw.get("every", 2)),
        within=float(raw.get("within", 60)),
        when=str(raw.get("when") or ""),
    )


def _operation(provider: str, name: str, raw: dict[str, Any]) -> Operation:
    method, _, path = str(raw.get("request", "")).partition(" ")
    price = raw.get("price") or {}
    if price == "free" or raw.get("free"):
        price = {"usd": 0}
    return Operation(
        provider=provider,
        name=name,
        title=str(raw.get("title") or name),
        method=method.upper(),
        path=path.strip(),
        params={p: _param(p, spec) for p, spec in (raw.get("params") or {}).items()},
        about=str(raw.get("about") or ""),
        docs=str(raw.get("docs") or ""),
        price=Price(
            usd=price.get("usd"),
            credits=price.get("credits"),
            per=str(price.get("per", "call")),
            note=str(price.get("note", "")),
        ),
        not_found=tuple(int(s) for s in _tuple(raw.get("not_found"))),
        no_match=str(raw.get("no_match") or ""),
        routes=tuple(_route(job, spec or {}) for job, spec in (raw.get("jobs") or {}).items()),
        body=str(raw.get("body") or "json"),
        api=str(raw.get("api") or "").rstrip("/"),
    )


def _key(raw: Any) -> Key:
    raw = raw or {}
    if raw.get("bearer"):
        return Key(env=raw["env"], header="Authorization", prefix="Bearer ", optional=bool(raw.get("optional")))
    return Key(
        env=str(raw.get("env", "")),
        header=str(raw.get("header", "")),
        prefix=str(raw.get("prefix", "")),
        query=str(raw.get("query", "")),
        basic=str(raw.get("basic", "")),
        body=str(raw.get("body", "")),
        also=tuple((str(a["header"]), str(a["env"])) for a in raw.get("also") or []),
        optional=bool(raw.get("optional")),
    )


def load_provider(path: Path) -> Provider:
    raw = yaml.safe_load(path.read_text()) or {}
    pid = str(raw.get("id") or path.stem)
    return Provider(
        id=pid,
        title=str(raw.get("title") or pid),
        api=str(raw.get("api") or "").rstrip("/"),
        key=_key(raw.get("key")),
        site=str(raw.get("site") or ""),
        docs=str(raw.get("docs") or ""),
        pricing=str(raw.get("pricing") or ""),
        credit_usd=raw.get("credit_usd"),
        about=str(raw.get("about") or ""),
        operations={n: _operation(pid, n, spec or {}) for n, spec in (raw.get("operations") or {}).items()},
    )


def default_dir() -> Path:
    return Path(str(resources.files("openpeoplerouter") / "providers"))


_WORD = re.compile(r"[a-z0-9]+")


class Catalog:
    def __init__(self, providers: dict[str, Provider], unreadable: list[str] | None = None):
        self.providers = providers
        self.unreadable = unreadable or []

    @classmethod
    def load(cls, directory: str | Path | None = None) -> "Catalog":
        root = Path(directory) if directory else default_dir()
        providers, unreadable = {}, []
        for path in sorted(root.glob("*.yaml")):
            try:
                provider = load_provider(path)
            except (yaml.YAMLError, AttributeError, TypeError, ValueError) as exc:
                unreadable.append(f"{path.name}: cannot be read: {str(exc).splitlines()[0]}")
                continue
            providers[provider.id] = provider
        return cls(providers, unreadable)

    @cached_property
    def operations(self) -> dict[str, Operation]:
        return {op.id: op for p in self.providers.values() for op in p.operations.values()}

    def routes(self, job: str) -> list[tuple[Operation, Route]]:
        return [(op, r) for op in self.operations.values() for r in op.routes if r.job == job]

    @cached_property
    def _index(self) -> list[tuple[Operation, set[str], set[str]]]:
        """Per operation: the words of its name and title, and every other word about it."""
        rows = []
        for op in self.operations.values():
            provider = self.providers[op.provider]
            strong = " ".join((op.id, op.title, provider.title))
            weak = " ".join((op.about, op.path, *(r.job for r in op.routes)))
            words = lambda text: set(_WORD.findall(text.lower().replace("_", " ")))  # noqa: E731
            rows.append((op, words(strong), words(weak)))
        return rows

    def search(self, query: str, limit: int = 10, keep=lambda op: True) -> list[Operation]:
        words = set(_WORD.findall(query.lower()))
        scored = []
        for op, strong, weak in self._index:
            if not keep(op):
                continue
            score = 2 * len(words & strong) + len(words & (weak - strong))
            if score:
                scored.append((-score, -len(op.routes), op.id, op))
        return [row[-1] for row in sorted(scored)[:limit]]

    def problems(self) -> list[str]:
        out: list[str] = list(self.unreadable)
        envs: dict[str, str] = {}
        for p in self.providers.values():
            where = f"{p.id}:"
            if not p.api.startswith("https://"):
                out.append(f"{where} api must be an https URL")
            if not p.docs:
                out.append(f"{where} docs link missing")
            k = p.key
            if k.env and not (k.header or k.query or k.basic or k.body):
                out.append(f"{where} key has env but no header, query, basic or body")
            if k.basic and k.basic not in ("user", "password"):
                out.append(f"{where} key.basic must be user or password")
            for env in k.envs():
                if envs.setdefault(env, p.id) != p.id:
                    out.append(f"{where} key env {env} already used by {envs[env]}")
            if not p.operations:
                out.append(f"{where} no operations")
            for op in p.operations.values():
                out.extend(f"{op.id}: {msg}" for msg in _op_problems(op))
                for r in op.routes:
                    if r.poll and r.poll.operation not in p.operations:
                        out.append(f"{op.id}: {r.job}: poll operation {r.poll.operation!r} not in {p.id}")
                    elif r.poll:
                        target = p.operations[r.poll.operation]
                        for param in r.poll.send:
                            if param not in target.params:
                                out.append(f"{op.id}: {r.job}: poll sends {param!r}, not a param of {target.id}")
        return out


def target_of(entry: Any) -> str:
    return str(entry["to"]) if isinstance(entry, dict) else str(entry)


def _root(op: Operation, target: Any) -> str:
    target = target_of(target)
    return target if target in op.params else target.removesuffix("[]").split(".")[0]


def _op_problems(op: Operation) -> list[str]:
    out = []
    if op.method not in METHODS:
        out.append(f"method {op.method!r} not one of {sorted(METHODS)}")
    if not op.path.startswith("/"):
        out.append("path must start with /")
    for name in re.findall(r"\{([^}]+)\}", op.path):
        if op.params.get(name, Param(name, at="?")).at != "path":
            out.append(f"path placeholder {{{name}}} has no `in: path` param")
    for p in op.params.values():
        if p.at not in LOCATIONS:
            out.append(f"param {p.name}: in {p.at!r} not one of {sorted(LOCATIONS)}")
        if p.type not in TYPES:
            out.append(f"param {p.name}: type {p.type!r} not one of {sorted(TYPES)}")
        if p.at == "path" and "{" + p.name + "}" not in op.path:
            out.append(f"param {p.name}: in path but the path has no {{{p.name}}}")
    if op.no_match:
        try:
            compile_expression(op.no_match)
        except Exception as exc:  # noqa: BLE001
            out.append(f"bad no_match expression: {exc}")
    if op.price.per not in PER:
        out.append(f"price.per {op.price.per!r} not one of {sorted(PER)}")
    if op.api and not op.api.startswith("https://"):
        out.append("api must be an https URL")
    if op.body not in ("json", "form", "whole"):
        out.append(f"body {op.body!r} not json, form or whole")
    if op.body == "whole" and len([p for p in op.params.values() if p.at == "body"]) != 1:
        out.append("body whole needs exactly one `in: body` param")
    for r in op.routes:
        job = JOBS.get(r.job)
        if job is None:
            out.append(f"job {r.job!r} is not one of {sorted(JOBS)}")
            continue
        allowed = set(job.inputs) | DERIVED
        if not r.needs:
            out.append(f"{r.job}: needs is empty")
        for option in r.needs:
            for name in option:
                if name not in allowed:
                    out.append(f"{r.job}: needs {name!r}, not an input of the job")
        for given, entry in r.send.items():
            param = target_of(entry)
            if given not in allowed:
                out.append(f"{r.job}: send {given!r} is not an input of the job")
            if param not in op.params and param.removesuffix("[]").split(".")[0] not in op.params:
                out.append(f"{r.job}: send to {param!r}, which is not a param")
        for param in r.fixed:
            if param.split(".")[0] not in op.params and param not in op.params:
                out.append(f"{r.job}: fixed {param!r} is not a param")
        if r.limit and r.limit not in op.params and r.limit.split(".")[0] not in op.params:
            out.append(f"{r.job}: limit {r.limit!r} is not a param")
        for name in [n for option in r.needs for n in option]:
            if name not in r.send and name != "platform" and not CARRIED_BY.get(name, set()) & set(r.send):
                out.append(f"{r.job}: needs {name!r} but never sends it")
                break
        if not set(r.audience) <= {*AUDIENCES, "any"}:
            out.append(f"{r.job}: audience {list(r.audience)} not among {[*AUDIENCES, 'any']}")
        if r.job == "read_profile" and not r.platform:
            out.append("read_profile: platform missing")
        if not set(r.fields) <= set(job.fields):
            out.append(f"{r.job}: fields {sorted(set(r.fields) - set(job.fields))} not in the job")
        for expr in [r.result, *r.fields.values()]:
            try:
                compile_expression(expr)
                unknown_function(expr)
            except Exception as exc:  # noqa: BLE001 — reported, not raised
                out.append(f"{r.job}: bad expression {expr!r}: {exc}")
        if r.poll:
            for expr in [r.poll.until, *r.poll.send.values(), *([r.poll.when] if r.poll.when else [])]:
                try:
                    compile_expression(expr)
                except Exception as exc:  # noqa: BLE001
                    out.append(f"{r.job}: bad poll expression {expr!r}: {exc}")
        required = {p.name for p in op.params.values() if p.required and p.default is None}
        for option in r.needs:
            names = set(option) | {d for n in option for d in CARRIED_BY.get(n, ())}
            sent = {_root(op, r.send[n]) for n in names if n in r.send} | {s.split(".")[0] for s in r.fixed}
            missing = required - sent
            if missing:
                out.append(f"{r.job}: needs {list(option)} leaves required {sorted(missing)} unsent")
                break
    return out
