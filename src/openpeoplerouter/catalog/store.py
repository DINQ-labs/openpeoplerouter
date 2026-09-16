"""Loading the catalog: YAML in, one immutable `Catalog` out.

Layout (`catalog/` at the repo root, or `OPENPEOPLEROUTER_CATALOG_DIR`):

    capabilities.yaml   what jobs exist, in the caller's words
    contracts.yaml      one contract per routed capability
    adapters.yaml       vendor endpoint -> contract wiring
    fx.yaml             vendor credits and other currencies -> USD
    vendors/*.yaml      one file per vendor: auth, base URL, endpoints

Nothing here talks to the network or to a database. A malformed vendor file is
reported and skipped rather than taking the catalog down; a missing directory
yields an empty catalog so the server still starts.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from openpeoplerouter.catalog.search_terms import normalize_query
from openpeoplerouter.catalog.models import Adapter, Auth, Contract, Cost, Endpoint, Vendor

logger = logging.getLogger("openpeoplerouter.catalog")

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data"

_STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "get", "how", "in", "is", "it", "of", "on", "or", "that", "the", "their", "to", "want", "with", "you", "your"]
)


@dataclass(frozen=True)
class Catalog:
    vendors: dict[str, Vendor] = field(default_factory=dict)
    endpoints: tuple[Endpoint, ...] = ()
    by_id: dict[str, Endpoint] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    order: tuple[str, ...] = ()  # the jobs in the order the work happens
    titles: dict[str, Any] = field(default_factory=dict)
    contracts: dict[str, Contract] = field(default_factory=dict)
    adapters: dict[str, Adapter] = field(default_factory=dict)
    verified: dict[str, bool] = field(default_factory=dict)
    ranks: dict[str, int] = field(default_factory=dict)  # endpoint id -> hand-set position within its capability
    rates_to_usd: dict[str, float] = field(default_factory=dict)
    credit_rates_usd: dict[str, float | None] = field(default_factory=dict)
    unit_rates_usd: dict[str, dict[str, float | None]] = field(default_factory=dict)
    problems: tuple[str, ...] = ()

    # ---- money ----------------------------------------------------------------------------------

    def usd(self, endpoint: Endpoint) -> float | None:
        """List price of one call in USD, or None when the vendor publishes none.

        None means unknown, never free: an endpoint with an unknown price is not
        offered on our own key."""
        cost = endpoint.cost
        if cost.type == "free":
            return 0.0
        if cost.value is None or cost.per <= 0:
            return None
        currency = (cost.currency or "USD").lower()
        if currency == "credit":
            rate = self.credit_rates_usd.get(endpoint.vendor)
        elif currency == "unit":
            rate = (self.unit_rates_usd.get(endpoint.vendor) or {}).get(cost.unit)
        else:
            rate = self.rates_to_usd.get(currency.upper())
        if rate is None:
            return None
        return round(cost.value * rate / cost.per, 9)

    def usd_at(self, endpoint: Endpoint, rows: int = 1) -> float | None:
        """Price for a request of this size. Per-row endpoints multiply."""
        unit = self.usd(endpoint)
        if unit is None:
            return None
        if endpoint.cost.type != "per_result":
            return unit
        per = max(endpoint.cost.per, 1)
        return round(unit * per * math.ceil(max(rows, 1) / per), 9)

    # ---- credentials ------------------------------------------------------------------------------

    def credential_present(self, vendor_id: str, env: dict[str, str] | None = None) -> bool:
        vendor = self.vendors.get(vendor_id)
        if vendor is None:
            return False
        if vendor.auth.kind == "none" or not vendor.auth.credential:
            return True
        source = env if env is not None else os.environ
        needed = [vendor.auth.credential] + [
            name for _, value in vendor.auth.extra_headers for name in re.findall(r"\$\{([A-Z0-9_]+)\}", value)
        ]
        return all((source.get(name) or "").strip() for name in needed)

    def live_endpoints(self, capability: str | None = None, env: dict[str, str] | None = None) -> list[Endpoint]:
        # A job's endpoints are the routed ones. A tool that happens to share the job's
        # name is reached by find_tool, not by the job, so it does not count toward it.
        return [
            ep
            for ep in self.endpoints
            if ep.live
            and (capability is None or (ep.capability == capability and not ep.tool))
            and self.credential_present(ep.vendor, env)
        ]

    # ---- discovery --------------------------------------------------------------------------------

    def capability_view(self, capability: str, env: dict[str, str] | None = None) -> dict[str, Any]:
        contract = self.contracts.get(capability)
        served = self.live_endpoints(capability, env)
        here = [e for e in self.endpoints if e.capability == capability and e.live]
        prices = [p for p in (self.usd(ep) for ep in served) if p is not None]
        row: dict[str, Any] = {
            "capability": capability,
            "title": self.title(capability),
            "summary": self.summary(capability),
            "vendors": sorted({ep.vendor for ep in served}),
            "endpoints": len(served),
            "in_catalog": len(here),
            "needs_key": sorted({self.vendors[ep.vendor].auth.credential for ep in here if ep not in served and self.vendors[ep.vendor].auth.credential}),
        }
        if prices:
            row["usd_per_call"] = [min(prices), max(prices)] if min(prices) != max(prices) else min(prices)
        if contract is not None:
            row["identity"] = ["{" + ", ".join(v) + "}" for v in contract.identity]
            row["output"] = list(contract.output)
        return row

    def title(self, capability: str, lang: str = "en") -> str:
        """The name a person reads. One source, so the agent and the website agree."""
        found = _in_language(self.titles.get(capability), lang)
        return found or capability.replace(".", " ").replace("_", " ").capitalize()

    def summary(self, capability: str, lang: str = "en") -> str:
        """What the job does, in the reader's language."""
        return _in_language(self.capabilities.get(capability), lang)

    def jobs(self) -> list[str]:
        """Every routed capability, in the order the work happens: find someone, work
        out who they are, then reach them. Six jobs do not need grouping; the order
        carries the meaning a heading would have. Anything unlisted follows."""
        named = [c for c in self.order if c in self.contracts]
        return named + sorted(c for c in self.contracts if c not in named)

    def search(self, query: str, limit: int = 8, env: dict[str, str] | None = None) -> list[Endpoint]:
        """Words in, endpoints out. Matches the capability, the name and the summary."""
        tokens = [t for t in re.findall(r"[a-z0-9.\u4e00-\u9fff]+", normalize_query(query or "").lower()) if t not in _STOPWORDS and (len(t) > 1 or t == "x")]
        if not tokens:
            return []
        scored: list[tuple[float, Endpoint]] = []
        for ep in self.endpoints:
            if not ep.live:
                continue
            haystacks = (
                (f"{ep.capability} {self.summary(ep.capability)}", 3.0),
                (f"{ep.name} {ep.summary}", 2.0),
                (f"{ep.id} {ep.vendor} {ep.path}", 1.0),
            )
            score = 0.0
            hits = 0
            for token in tokens:
                best = 0.0
                for text, weight in haystacks:
                    if (re.search(r"(?<![a-z])x(?![a-z])", text.lower()) if token == "x" else token in text.lower()):
                        best = max(best, weight)
                if best:
                    hits += 1
                    score += best
            if hits < max(1, len(tokens) - len(tokens) // 3):
                continue
            if self.credential_present(ep.vendor, env):
                score += 1.5
            if ep.tier == "core":
                score += 0.5
            scored.append((score, ep))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [ep for _, ep in scored[:limit]]


# ---- parsing ------------------------------------------------------------------------------------------


def _in_language(value: Any, lang: str) -> str:
    """A catalog string is either one language or a map of them. English is the
    fallback, because every string has it."""
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or next(iter(value.values()), ""))
    return str(value or "")


def _flat_inputs(raw: Any) -> dict[str, Any]:
    """One shape for an endpoint's inputs: {queryParams, body, pathParams} each a flat map of
    parameter -> {type, required, note}. Vendor files write a POST body as a JSON-schema
    object with `properties`; callers and the relay should never have to know that."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for where in ("queryParams", "body", "pathParams"):
        section = raw.get(where)
        if not isinstance(section, dict):
            continue
        if isinstance(section.get("properties"), dict) and "type" in section:
            required = section.get("required")
            props = {k: (dict(v) if isinstance(v, dict) else {"type": "string"}) for k, v in section["properties"].items()}
            if isinstance(required, list):
                for k in required:
                    if k in props:
                        props[k]["required"] = True
            out[where] = props
        else:
            out[where] = section
    for key, value in raw.items():
        if key not in out and key not in ("queryParams", "body", "pathParams"):
            out[key] = value
    return out


def _cost(raw: Any) -> Cost:
    if not isinstance(raw, dict):
        return Cost(type="per_call", value=None, confidence="unknown")
    return Cost(
        type=str(raw.get("type") or "per_call"),
        value=raw.get("value"),
        currency=str(raw.get("currency") or "USD"),
        per=int(raw.get("per") or 1),
        unit=str(raw.get("unit") or "call"),
        source=str(raw.get("source") or ""),
        source_url=str(raw.get("source_url") or ""),
        checked=str(raw.get("checked") or ""),
        confidence=str(raw.get("confidence") or "unknown"),
        note=str(raw.get("note") or ""),
    )


def _auth(raw: Any) -> Auth:
    if not isinstance(raw, dict):
        return Auth(kind="none", credential="")
    extra = raw.get("extra_headers") or {}
    return Auth(
        kind=str(raw.get("kind") or "header"),
        name=str(raw.get("name") or "Authorization"),
        format=str(raw.get("format") or "{secret}"),
        credential=str(raw.get("credential") or ""),
        extra_headers=tuple((str(k), str(v)) for k, v in extra.items()) if isinstance(extra, dict) else (),
    )


def _vendor_file(doc: dict[str, Any], problems: list[str], source: str) -> tuple[Vendor | None, list[Endpoint]]:
    vendor_id = str(doc.get("vendor") or "").strip()
    if not vendor_id:
        problems.append(f"{source}: no `vendor:`")
        return None, []
    vendor = Vendor(
        id=vendor_id,
        name=str(doc.get("name") or vendor_id),
        base_url=str(doc.get("base_url") or "").rstrip("/"),
        auth=_auth(doc.get("auth")),
        docs=str(doc.get("docs") or ""),
        pricing_url=str(doc.get("pricing_url") or ""),
        limits=str(doc.get("limits") or ""),
        homepage=str(doc.get("homepage") or ""),
    )
    endpoints: list[Endpoint] = []
    for raw in doc.get("endpoints") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            problems.append(f"{source}: an endpoint has no id")
            continue
        endpoint_id = str(raw["id"])
        if not raw.get("capability"):
            problems.append(f"{endpoint_id}: no capability")
            continue
        if not raw.get("path"):
            problems.append(f"{endpoint_id}: needs a path")
            continue
        notes = raw.get("notes") or []
        miss_raw = raw.get("miss")
        miss_status = miss_raw.get("status") if isinstance(miss_raw, dict) else None
        miss_note = (miss_raw.get("means", "") if isinstance(miss_raw, dict) else str(miss_raw or ""))
        endpoints.append(
            Endpoint(
                id=endpoint_id,
                vendor=vendor_id,
                capability=str(raw["capability"]),
                name=str(raw.get("name") or ""),
                summary=str(raw.get("summary") or ""),
                method=str(raw.get("method") or "GET").upper(),
                path=str(raw.get("path") or ""),
                inputs=_flat_inputs(raw.get("input")),
                cost=_cost(raw.get("cost")),
                latency=str(raw.get("latency") or ""),
                docs_url=str(raw.get("docs_url") or ""),
                tier=str(raw.get("tier") or "core"),
                tool=bool(raw.get("tool")),
                status=str(raw.get("status") or ""),
                status_note=str(raw.get("status_note") or ""),
                miss_note=str(miss_note or ""),
                miss_status=int(miss_status) if miss_status is not None else None,
                notes=tuple(str(n) for n in notes),
                provides=tuple(str(x) for x in (raw.get("provides") or ())),
                test_request=raw.get("test_request") or {},
            )
        )
    return vendor, endpoints


def _contracts(doc: Any) -> dict[str, Contract]:
    out: dict[str, Contract] = {}
    for capability, raw in (doc or {}).get("contracts", {}).items():
        identity_types: dict[str, str] = {}
        variants: list[tuple[str, ...]] = []
        for variant in raw.get("identity") or []:
            if isinstance(variant, dict):
                identity_types.update({str(k): str(v) for k, v in variant.items()})
                variants.append(tuple(sorted(str(k) for k in variant)))
            elif isinstance(variant, list):
                identity_types.update({str(k): "str" for k in variant})
                variants.append(tuple(sorted(str(k) for k in variant)))
        output = {str(k): (v if isinstance(v, dict) else {}) for k, v in (raw.get("output") or {}).items()}
        list_field = next((k for k, spec in output.items() if spec.get("type") == "list" and spec.get("required")), "")
        out[capability] = Contract(
            capability=capability,
            summary=str(raw.get("summary") or ""),
            identity=tuple(variants),
            identity_types=identity_types,
            aliases={str(k): str(v) for k, v in (raw.get("aliases") or {}).items()},
            derive={str(k): str(v) for k, v in (raw.get("derive") or {}).items()},
            filters={str(k): (v if isinstance(v, dict) else {}) for k, v in (raw.get("filters") or {}).items()},
            output=output,
            miss=str(raw.get("miss") or ""),
            list_field=list_field,
            row_key=str(raw.get("row_key") or ""),
            merge=str(raw.get("merge") or ""),
        )
    return out


def _adapters(doc: Any, contracts: dict[str, Contract], by_id: dict[str, Endpoint], problems: list[str]) -> dict[str, Adapter]:
    out: dict[str, Adapter] = {}
    for endpoint_id, raw in (doc or {}).get("adapters", {}).items():
        endpoint = by_id.get(endpoint_id)
        if endpoint is None:
            problems.append(f"adapter {endpoint_id}: no such endpoint")
            continue
        contract = contracts.get(endpoint.capability)
        if contract is None:
            problems.append(f"adapter {endpoint_id}: capability {endpoint.capability} has no contract")
            continue
        accepts = tuple(tuple(sorted(str(k) for k in variant)) for variant in raw.get("accepts") or [])
        canonical = tuple(
            tuple(sorted(contract.aliases.get(field, field) for field in variant)) for variant in accepts
        )
        unknown = [raw_variant for raw_variant, named in zip(accepts, canonical, strict=True) if named not in contract.identity]
        if unknown:
            problems.append(f"adapter {endpoint_id}: accepts a variant the contract does not define: {unknown}")
        out_map = {str(k): str(v) for k, v in (raw.get("out") or {}).items()}
        missing = [f for f in contract.required_output if f not in out_map]
        if missing:
            problems.append(f"adapter {endpoint_id}: does not map required output {missing}")
            continue
        when_raw = raw.get("when") or []
        when = (str(when_raw),) if isinstance(when_raw, str) else tuple(str(w) for w in when_raw)
        out[endpoint_id] = Adapter(
            endpoint_id=endpoint_id,
            accepts=accepts,
            in_map={str(k): str(v) for k, v in (raw.get("in") or {}).items()},
            in_expr={str(k): str(v) for k, v in (raw.get("in_expr") or {}).items()},
            const=raw.get("const") or {},
            out_map=out_map,
            miss=str(raw.get("miss") or ""),
            body_array=bool(raw.get("body_array")),
            filter_keys=tuple(contract.filters),
            when=when,
        )
    return out


def _verify(
    adapters: dict[str, Adapter],
    contracts: dict[str, Contract],
    by_id: dict[str, Endpoint],
    examples_dir: Path,
    problems: list[str],
) -> dict[str, bool]:
    """Replay each captured vendor response through its adapter.

    A mapping written from documentation is a guess until a real response goes
    through it. `catalog/examples/<endpoint id>.json` is that response; if the
    adapter cannot turn it into either a miss or a complete answer, the mapping is
    wrong and says so at load, not in front of a customer."""
    verified: dict[str, bool] = {}
    if not examples_dir.is_dir():
        return verified
    for endpoint_id, adapter in adapters.items():
        path = examples_dir / f"{endpoint_id}.json"
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"example {path.name}: {exc}")
            continue
        contract = contracts.get(by_id[endpoint_id].capability)
        if contract is None:
            continue
        if adapter.is_miss(doc):
            verified[endpoint_id] = True
            continue
        output = adapter.from_upstream(doc)
        empty = [f for f in contract.required_output if output.get(f) in (None, "", [], {})]
        if empty:
            problems.append(
                f"adapter {endpoint_id}: the captured response is not a miss, but the mapping leaves {empty} empty"
            )
            verified[endpoint_id] = False
            continue
        # A list answer is rows an agent will carry into the next job, so every row has
        # to say who it is. Passing a vendor's rows through untouched used to count as
        # verified; it is not.
        rows = output.get(contract.list_field) if contract.list_field and contract.row_key else None
        key = contract.row_key
        nameless = [i for i, row in enumerate(rows or []) if not isinstance(row, dict) or not row.get(key)]
        if nameless:
            problems.append(
                f"adapter {endpoint_id}: {len(nameless)} of {len(rows)} rows in `{contract.list_field}` have no {key}"
            )
            verified[endpoint_id] = False
        else:
            verified[endpoint_id] = True
    return verified


_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _read(path: Path, problems: list[str]) -> dict[str, Any]:
    try:
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_LOADER)
    except (OSError, yaml.YAMLError) as exc:
        problems.append(f"{path.name}: {exc}")
        return {}
    return loaded if isinstance(loaded, dict) else {}


def load_catalog(directory: str | Path | None = None) -> Catalog:
    root = Path(directory or os.getenv("OPENPEOPLEROUTER_CATALOG_DIR") or DEFAULT_DIR)
    problems: list[str] = []
    if not root.is_dir():
        logger.warning("catalog directory %s not found; running with an empty catalog", root)
        return Catalog(problems=(f"catalog directory {root} not found",))

    caps_doc = _read(root / "capabilities.yaml", problems)
    capabilities = dict((caps_doc.get("capabilities") or {}).items())
    order = tuple(str(c) for c in (caps_doc.get("order") or []))
    titles = dict((caps_doc.get("titles") or {}).items())

    fx = _read(root / "fx.yaml", problems)
    rates = {str(k).upper(): float(v) for k, v in (fx.get("rates_to_usd") or {}).items()}
    credit_rates = {
        str(k): (None if (v or {}).get("usd") is None else float(v["usd"]))
        for k, v in (fx.get("credit_rates_usd") or {}).items()
    }
    unit_rates = {
        str(vendor): {str(meter): (None if (spec or {}).get("usd") is None else float(spec["usd"])) for meter, spec in meters.items()}
        for vendor, meters in (fx.get("unit_rates_usd") or {}).items()
    }

    vendors: dict[str, Vendor] = {}
    endpoints: list[Endpoint] = []
    by_id: dict[str, Endpoint] = {}
    for path in sorted((root / "vendors").glob("*.yaml")) if (root / "vendors").is_dir() else []:
        vendor, rows = _vendor_file(_read(path, problems), problems, path.name)
        if vendor is None:
            continue
        vendors[vendor.id] = vendor
        for ep in rows:
            if ep.id in by_id:
                problems.append(f"{ep.id}: duplicate endpoint id")
                continue
            by_id[ep.id] = ep
            endpoints.append(ep)

    contracts = _contracts(_read(root / "contracts.yaml", problems))
    adapters = _adapters(_read(root / "adapters.yaml", problems), contracts, by_id, problems)
    verified = _verify(adapters, contracts, by_id, root / "examples", problems)

    for ep in endpoints:
        if ep.capability not in capabilities and not ep.tool:
            problems.append(f"{ep.id}: capability {ep.capability} is not in capabilities.yaml")

    ranks: dict[str, int] = {}
    if (root / "ranks.yaml").is_file():
        for ids in (_read(root / "ranks.yaml", problems).get("ranks") or {}).values():
            for position, endpoint_id in enumerate(ids or []):
                ranks[str(endpoint_id)] = position

    if problems:
        logger.warning("catalog loaded with %d problem(s): %s", len(problems), "; ".join(problems[:5]))
    return Catalog(
        vendors=vendors,
        endpoints=tuple(endpoints),
        by_id=by_id,
        capabilities=capabilities,
        order=order,
        titles=titles,
        contracts=contracts,
        adapters=adapters,
        verified=verified,
        ranks=ranks,
        rates_to_usd=rates,
        credit_rates_usd=credit_rates,
        unit_rates_usd=unit_rates,
        problems=tuple(problems),
    )


@lru_cache(maxsize=4)
def _cached(directory: str) -> Catalog:
    return load_catalog(directory)


def catalog(directory: str | Path | None = None) -> Catalog:
    """The process-wide catalog. Cached; call `reload()` in tests."""
    return _cached(str(directory or os.getenv("OPENPEOPLEROUTER_CATALOG_DIR") or DEFAULT_DIR))


def reload() -> None:
    _cached.cache_clear()
