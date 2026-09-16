"""What a catalog is made of.

A **vendor** is a company with an API and one credential. An **endpoint** is one
call that vendor sells, tagged with the **capability** it answers. A **contract**
says what a capability takes and returns no matter who serves it. An **adapter**
is the one thing that has to be written per vendor per capability: how this
vendor's request and response line up with the contract.

Adding a vendor is a YAML file plus one adapter block. No Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openpeoplerouter.catalog.paths import evaluate, set_path

# ---- price ------------------------------------------------------------------------------------------

BILLING_TYPES = ("free", "per_call", "per_success", "per_result")


@dataclass(frozen=True)
class Cost:
    """What one call costs at the vendor, before our margin.

    `per_success` is the one that matters: the vendor bills only when data comes
    back, so a miss is free and the router can keep walking down the list."""

    type: str = "per_call"
    value: float | None = None
    currency: str = "USD"
    per: int = 1
    unit: str = "call"
    source: str = ""
    source_url: str = ""
    checked: str = ""
    confidence: str = "unknown"
    note: str = ""

    @property
    def free(self) -> bool:
        return self.type == "free" or self.value == 0

    @property
    def billed_on_miss(self) -> bool:
        return self.type in ("per_call", "per_result")

    def view(self, usd: float | None) -> dict[str, Any]:
        row: dict[str, Any] = {"type": self.type, "usd": usd, "unit": self.unit}
        if self.confidence != "verified":
            row["confidence"] = self.confidence
        if self.note:
            row["note"] = self.note
        return row


@dataclass(frozen=True)
class Auth:
    """How the vendor's credential rides on the request.

    `credential` is the env name; the value never appears in the catalog."""

    kind: str = "header"  # header | query | basic | none
    name: str = "Authorization"
    format: str = "Bearer {secret}"
    credential: str = ""
    extra_headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Vendor:
    id: str
    name: str
    base_url: str = ""
    auth: Auth = field(default_factory=Auth)
    docs: str = ""
    pricing_url: str = ""
    limits: str = ""
    homepage: str = ""

    def view(self) -> dict[str, Any]:
        return {
            "vendor": self.id,
            "name": self.name,
            "docs": self.docs,
            "pricing_url": self.pricing_url,
            "limits": self.limits,
            "credential": self.auth.credential,
        }


@dataclass(frozen=True)
class Endpoint:
    """One call at one vendor."""

    id: str
    vendor: str
    capability: str
    name: str = ""
    summary: str = ""
    method: str = "GET"
    path: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    cost: Cost = field(default_factory=Cost)
    latency: str = ""
    docs_url: str = ""
    tier: str = "core"
    status: str = ""  # "" | retired | broken
    tool: bool = False  # no contract: reached by find_tool / call_tool, never routed by job
    status_note: str = ""
    miss_note: str = ""
    miss_status: int | None = None  # a status the vendor uses to say "nobody matched"
    notes: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()  # for a capability with kinds of answer: email, phone…
    test_request: dict[str, Any] = field(default_factory=dict)

    @property
    def live(self) -> bool:
        return not self.status

    def view(self, *, usd: float | None = None, full: bool = False) -> dict[str, Any]:
        row: dict[str, Any] = {
            "endpoint": self.id,
            "vendor": self.vendor,
            "capability": self.capability,
            "name": self.name or self.id,
            "cost": self.cost.view(usd),
            "latency": self.latency,
        }
        if self.tool:
            row["tool"] = True
        if full:
            row.update(
                {
                    "summary": self.summary,
                    "method": self.method,
                    "path": self.path,
                    "inputs": self.inputs,
                    "docs_url": self.docs_url,
                    "miss": self.miss_note,
                    "miss_status": self.miss_status,
                    "notes": list(self.notes),
                    "provides": list(self.provides),
                }
            )
        if self.status:
            row["status"] = self.status
            row["status_note"] = self.status_note
        return row


# ---- contracts ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Contract:
    """One capability, the same shape whoever serves it."""

    capability: str
    summary: str
    identity: tuple[tuple[str, ...], ...] = ()  # variants, each a sorted tuple of keys
    identity_types: dict[str, str] = field(default_factory=dict)
    # Two spellings of one input. Vendors disagree — Apollo takes `query` where Exa and
    # Hunter take `q` — so the contract names one and records the rest as aliases. The
    # caller only ever needs the canonical name; both reach the adapters.
    aliases: dict[str, str] = field(default_factory=dict)
    derive: dict[str, str] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    output: dict[str, dict] = field(default_factory=dict)
    miss: str = ""
    list_field: str = ""  # the required list field, when the answer is rows
    row_key: str = ""  # what every row of that list must carry: a person's name, a profile's url
    merge: str = ""  # a list field to union across vendors instead of stopping at the first hit

    @property
    def required_output(self) -> tuple[str, ...]:
        return tuple(k for k, spec in self.output.items() if spec.get("required"))

    def is_miss(self, output: dict[str, Any]) -> bool:
        if self.miss and bool(evaluate(self.miss, output)):
            return True
        return any(output.get(k) in (None, "", [], {}) for k in self.required_output)

    def view(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "summary": self.summary,
            "identity": ["{" + ", ".join(v) + "}" for v in self.identity],
            "aliases": dict(self.aliases),
            "filters": {k: spec.get("note", "") for k, spec in self.filters.items()},
            "output": list(self.output),
            "miss": self.miss,
        }


def _derive_inputs(contract: Contract) -> set[str]:
    """Names a derive expression reads, so `first_name` survives long enough to
    become `full_name` even though no variant names it."""
    import re as _re

    return {word for expr in contract.derive.values() for word in _re.findall(r"[a-z_][a-z0-9_]*", expr)}


def canonical_identity(contract: Contract, supplied: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...] | None]:
    """Keep the keys this contract knows, find the variant the caller satisfies, then
    fill in everything derivable. Returns (identity, matched variant or None)."""
    known = set(contract.identity_types) | _derive_inputs(contract) | set(contract.aliases)
    ident = {k: v for k, v in supplied.items() if k in known and v not in (None, "", [], {})}
    for alias, canonical in contract.aliases.items():  # either spelling reaches every adapter
        if ident.get(canonical) in (None, "") and ident.get(alias) not in (None, ""):
            ident[canonical] = ident[alias]
        elif ident.get(alias) in (None, "") and ident.get(canonical) not in (None, ""):
            ident[alias] = ident[canonical]
    matched = next((v for v in contract.identity if all(k in ident for k in v)), None)
    if matched is None:
        return ident, None
    for _ in range(2):  # full_name -> first/last -> join, and back
        for field_name, expr in contract.derive.items():
            if ident.get(field_name) in (None, "", [], {}):
                value = evaluate(expr, ident)
                if value not in (None, "", [], {}):
                    ident[field_name] = value
    for name, spec in contract.filters.items():
        if name not in supplied or supplied[name] in (None, ""):
            if spec.get("default") is not None:
                ident[name] = spec["default"]
        else:
            ident[name] = supplied[name]
    return ident, matched


# ---- adapters -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Adapter:
    """The vendor-to-contract wiring for one endpoint."""

    endpoint_id: str
    accepts: tuple[tuple[str, ...], ...] = ()
    in_map: dict[str, str] = field(default_factory=dict)  # contract field -> query.x | body.a.b | path.x
    in_expr: dict[str, str] = field(default_factory=dict)  # target -> expression over the identity
    const: dict[str, Any] = field(default_factory=dict)
    out_map: dict[str, str] = field(default_factory=dict)  # contract field -> expression over the body
    miss: str = ""
    body_array: bool = False
    filter_keys: tuple[str, ...] = ()
    when: tuple[str, ...] = ()  # extra conditions on the identity; any one true is enough

    def accepts_variant(self, variant: tuple[str, ...] | None) -> bool:
        return variant is not None and variant in self.accepts

    def applies(self, identity: dict[str, Any]) -> bool:
        """`when` keeps a GitHub URL out of Hugging Face: same identity shape, wrong host."""
        if not self.when:
            return True
        return any(bool(evaluate(cond, identity)) for cond in self.when)

    def to_upstream(self, identity: dict[str, Any], variant: tuple[str, ...]) -> tuple[dict[str, str], dict[str, Any], dict[str, str]]:
        """Build (query, body, path params) for one call.

        Only the matched variant's identity keys are sent — a vendor asked for a
        LinkedIn URL should not also receive a half-guessed name — but every
        contract filter rides along, because that is what the caller asked for."""
        query: dict[str, str] = {}
        body: dict[str, Any] = {}
        path_params: dict[str, str] = {}
        wanted = set(variant) | set(self.filter_keys)
        for field_name, target in self.in_map.items():
            if field_name not in wanted:
                continue
            value = identity.get(field_name)
            if value in (None, "", [], {}):
                continue
            self._place(target, value, query, body, path_params)
        for target, expr in self.in_expr.items():
            value = evaluate(expr, identity)
            if value in (None, "", [], {}):
                continue
            self._place(target, value, query, body, path_params)
        for target, value in self.const.items():
            self._place(target, value, query, body, path_params)
        return query, body, path_params

    @staticmethod
    def _place(target: str, value: Any, query: dict[str, str], body: dict[str, Any], path_params: dict[str, str]) -> None:
        where, _, name = target.partition(".")
        if where == "body":
            set_path(body, name, value)
        elif where == "path":
            path_params[name] = str(value)
        else:  # query
            query[name] = str(value) if not isinstance(value, bool) else ("true" if value else "false")

    def from_upstream(self, doc: Any) -> dict[str, Any]:
        return {field_name: evaluate(expr, doc) for field_name, expr in self.out_map.items()}

    def is_miss(self, doc: Any) -> bool:
        return bool(evaluate(self.miss, doc)) if self.miss else False
