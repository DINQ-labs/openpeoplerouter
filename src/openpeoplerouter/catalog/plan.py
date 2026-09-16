"""Which vendors can answer this, in what order, and what each would cost.

The plan is made before any network call and is shown to the caller. Ordering is:

1. **specificity** — a vendor that was given the exact identity the caller has
   beats one that had to work from a derived name.
2. **ignored filters** — a vendor that drops a filter the caller set is answering
   a looser question, so it ranks below one that honours it, but stays reachable.
3. **expected cost per hit** — not the list price. A vendor that costs twice as
   much but answers three times as often is cheaper per answer, and a vendor that
   only bills on success costs nothing for its misses.
4. speed, then the endpoint id, so the order is stable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from openpeoplerouter.catalog.models import Adapter, Contract, Endpoint, canonical_identity
from openpeoplerouter.catalog.store import Catalog

@dataclass
class Candidate:
    endpoint: Endpoint
    adapter: Adapter
    variant: tuple[str, ...]
    usd: float | None
    ignored: tuple[str, ...] = ()
    covers: int = 0

    def view(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "endpoint": self.endpoint.id,
            "vendor": self.endpoint.vendor,
            "usd": self.usd,
            "billing": self.endpoint.cost.type,
            "latency": self.endpoint.latency,
            "using": "{" + ", ".join(self.variant) + "}",
        }
        if self.ignored:
            row["ignores"] = list(self.ignored)
        return row


@dataclass
class Plan:
    capability: str
    contract: Contract | None
    identity: dict[str, Any] = field(default_factory=dict)
    variant: tuple[str, ...] | None = None
    candidates: list[Candidate] = field(default_factory=list)
    dropped: list[dict[str, str]] = field(default_factory=list)

    @property
    def cheapest(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    def view(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "capability": self.capability,
            "identified_by": "{" + ", ".join(self.variant) + "}" if self.variant else None,
            "will_try": [c.view() for c in self.candidates],
        }
        if self.dropped:
            row["not_tried"] = self.dropped
        return row


def ignored_filters(adapter: Adapter, contract: Contract, identity: dict[str, Any]) -> tuple[str, ...]:
    """Filters the caller set that this vendor has no way to receive."""
    wired = set(adapter.in_map) | {t for expr in adapter.in_expr.values() for t in _identifiers(expr)}
    return tuple(
        name
        for name in contract.filters
        if identity.get(name) not in (None, "", [], {}) and name not in wired
    )


def _identifiers(expr: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z_][a-z0-9_]*", expr or ""))


def _wanted(endpoint: Endpoint, identity: dict[str, Any]) -> bool:
    """A phone costs several times what an email does, so a caller who asked for an
    email is never quietly charged for a phone lookup."""
    if not endpoint.provides:
        return True
    want = str(identity.get("want") or "both").lower()
    return want in ("both", "any") or want in endpoint.provides


def _covers(variant: tuple[str, ...], supplied: dict[str, Any], contract: Contract) -> int:
    """How much of what the caller actually sent this variant uses directly."""
    given = {k for k, v in supplied.items() if v not in (None, "", [], {})}
    direct = len(given & set(variant))
    derived = sum(1 for k in variant if k not in given and k in contract.derive)
    return direct * 2 - derived


def candidates_for(
    catalog: Catalog,
    capability: str,
    supplied: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
    exclude: set[str] | None = None,
) -> Plan:
    contract = catalog.contracts.get(capability)
    plan = Plan(capability=capability, contract=contract)
    if contract is None:
        return plan
    identity, variant = canonical_identity(contract, supplied)
    plan.identity, plan.variant = identity, variant
    if variant is None:
        return plan

    exclude = exclude or set()
    rows = int(identity.get("limit") or 1)
    for endpoint in catalog.endpoints:
        if endpoint.capability != capability or not endpoint.live or endpoint.tool:
            continue
        if endpoint.vendor in exclude or endpoint.id in exclude:
            continue
        adapter = catalog.adapters.get(endpoint.id)
        if adapter is None:
            plan.dropped.append({"endpoint": endpoint.id, "why": "no adapter, so it cannot be routed"})
            continue
        if not catalog.credential_present(endpoint.vendor, env):
            plan.dropped.append({"endpoint": endpoint.id, "why": f"no {catalog.vendors[endpoint.vendor].auth.credential} on this server"})
            continue
        served = next((v for v in adapter.accepts if all(k in identity for k in v)), None)
        if served is None:
            wants = " | ".join("{" + ", ".join(v) + "}" for v in adapter.accepts)
            plan.dropped.append({"endpoint": endpoint.id, "why": f"needs {wants}"})
            continue
        if not adapter.applies(identity):
            continue  # wrong host for this vendor; not a failure worth reporting
        if not _wanted(endpoint, identity):
            continue  # this vendor returns a kind of answer the caller did not ask for
        usd = catalog.usd_at(endpoint, rows)
        plan.candidates.append(
            Candidate(
                endpoint=endpoint,
                adapter=adapter,
                variant=served,
                usd=usd,
                ignored=ignored_filters(adapter, contract, identity),
                covers=_covers(served, supplied, contract),
            )
        )
    plan.candidates.sort(key=lambda c: sort_key(catalog, c))
    return plan


def sort_key(catalog: Catalog, c: Candidate) -> tuple:
    """The capability's stored order is the order the waterfall walks. An endpoint not in
    it yet (new since the order was saved) comes after, by list price."""
    rank = catalog.ranks.get(c.endpoint.id)
    if rank is not None:
        return (0, rank, 0.0, c.endpoint.id)
    return (1, 0, c.usd if c.usd is not None else float("inf"), c.endpoint.id)
