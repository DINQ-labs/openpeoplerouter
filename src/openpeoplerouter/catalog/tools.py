"""One MCP tool per capability, generated from the catalog.

The tool surface used to be hand-written while the catalog was data, and the two
drifted: the description still said "four jobs" after there were seven, and
`social.profile` had no parameter that could carry a profile URL, so it was not
merely undocumented — it was uncallable. A hand-written union of every
capability's inputs cannot stay honest, because nothing fails when a contract
gains a field.

So the tools come from the contracts. A capability's identity variants become its
parameters, its filters become the rest, and its summary, its price and how many
vendors are ready become its description. Add a capability to the catalog and the
agent can call it; change what a capability accepts and the schema changes with
it. There is no second place to update.

Each tool answers in the same envelope, so an agent learns the shape once.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from pydantic import Field

from openpeoplerouter.catalog.models import Contract, _derive_inputs
from openpeoplerouter.catalog.store import Catalog

Runner = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]

PYTHON_TYPES: dict[str, type] = {"str": str, "url": str, "int": int, "bool": bool, "float": float}

# What a field looks like, for the handful whose format an agent cannot guess. A field
# with no hint still becomes a parameter; this only makes the good ones clearer.
HINTS: dict[str, str] = {
    "linkedin_url": "https://www.linkedin.com/in/<slug>",
    "linkedin_handle": "The <slug> from a LinkedIn URL, without the /in/",
    "github_url": "https://github.com/<login>",
    "scholar_url": "https://scholar.google.com/citations?user=<id>",
    "huggingface_url": "https://huggingface.co/<login>",
    "x_handle": "@handle, or https://x.com/<handle>",
    "profile_url": "A profile page on any platform: linkedin.com, x.com, instagram.com, tiktok.com, github.com …",
    "platform": "linkedin | x | instagram | tiktok | youtube | github | threads | facebook | reddit | bluesky | weibo | douyin | xiaohongshu | bilibili | kuaishou",
    "handle": "The account name on that platform, without the @",
    "domain": "The employer's domain, no www and no @",
    "company_domain": "Search inside one company by its domain",
    "company_website": "The employer's website, when you have a URL rather than a bare domain",
    "email": "A work email address",
    "full_name": "The person's full name",
    "first_name": "Given name; pair it with last_name",
    "last_name": "Family name; pair it with first_name",
    "company": "The employer's name",
    "name": "The company's name",
    "website": "The company's website",
    "source_url": "A page that names people: a repository, a paper, a LinkedIn company page, a Crunchbase profile",
    "company_name": "A company name, to read its people and coverage",
    "q": "Free text describing who or what you are looking for",
    "query": "Free text describing who or what you are looking for",
    "title": "The role, written the way a company would write it",
    "industry": "An industry, as the provider names it",
    "technology": "A technology a company uses, e.g. snowflake",
}

ENVELOPE = "Returns outcome, normalized output, raw provider data and _meta.tried. Provider API charges are billed directly to your provider account."

def tool_name(capability: str) -> str:
    """`people.contact.find` -> `people_contact_find`. The id stays visible, because it is
    the same id the catalog pages and `capabilities` use."""
    return capability.replace(".", "_").replace("-", "_")


def _inputs(contract: Contract) -> dict[str, tuple[type, str]]:
    """Every field this capability can be given: the identity variants, anything a
    derive expression can build one from, and the filters."""
    fields: dict[str, tuple[type, str]] = {}
    for name in [f for variant in contract.identity for f in variant]:
        kind = PYTHON_TYPES.get(contract.identity_types.get(name, "str"), str)
        fields[name] = (kind, HINTS.get(name, ""))
    for name in sorted(_derive_inputs(contract) - set(fields)):
        if name in HINTS:  # a derive expression reads it, so it is a real input
            fields[name] = (str, HINTS[name])
    for name, spec in contract.filters.items():
        kind = PYTHON_TYPES.get(str(spec.get("type") or "str"), str)
        note = str(spec.get("note") or "")
        default = spec.get("default")
        fields[name] = (kind, f"{note} (default {default})" if default is not None else note)
    return fields


def describe(catalog: Catalog, capability: str) -> str:
    contract = catalog.contracts[capability]
    return contract.summary + " Use vendor to pin a provider. " + ENVELOPE


def build_tool(
    catalog: Catalog,
    capability: str,
    run: Runner,
    *,
    context_param: str = "ctx",
    context_type: Any = None,
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """One capability, as a function whose signature is the contract."""
    fields = _inputs(catalog.contracts[capability])
    routing: dict[str, tuple[Any, Any, str]] = {
        "vendor": (str | None, None, "Pin one vendor or endpoint id instead of routing"),
        "waterfall": (bool, True, "False stops at the first vendor instead of trying the next"),
    }
    subject = set(fields)

    async def call(**given: Any) -> dict[str, Any]:
        ctx = given.pop(context_param, None)
        options = {name: given.pop(name, None) for name in routing}
        return await run(capability, {k: v for k, v in given.items() if v not in (None, "")}, {**options, "ctx": ctx})

    annotations: dict[str, Any] = {}
    parameters: list[inspect.Parameter] = []
    for name, (kind, note) in sorted(fields.items(), key=lambda kv: (kv[0] not in subject, kv[0])):
        optional = kind | None if kind is not bool else bool
        default = False if kind is bool else None
        annotations[name] = Annotated[optional, Field(default=default, description=note)]
        parameters.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotations[name]))
    for name, (kind, default, note) in routing.items():
        annotations[name] = Annotated[kind, Field(default=default, description=note)]
        parameters.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotations[name]))
    if context_type is not None:
        annotations[context_param] = context_type
        parameters.append(inspect.Parameter(context_param, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=context_type))

    call.__name__ = tool_name(capability)
    call.__doc__ = describe(catalog, capability)
    call.__annotations__ = {**annotations, "return": dict[str, Any]}
    call.__signature__ = inspect.Signature(parameters, return_annotation=dict[str, Any])  # type: ignore[attr-defined]
    return call


def capability_tools(
    catalog: Catalog,
    run: Runner,
    *,
    context_type: Any = None,
) -> list[tuple[str, str, Callable[..., Awaitable[dict[str, Any]]]]]:
    """(name, description, function) for every capability the catalog serves."""
    out = []
    for capability in catalog.jobs():
        fn = build_tool(catalog, capability, run, context_type=context_type)
        out.append((tool_name(capability), fn.__doc__ or "", fn))
    return out

