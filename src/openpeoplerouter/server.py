"""The MCP server: one tool per job, plus direct access to every operation."""

from __future__ import annotations

from inspect import Parameter, Signature
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools import Tool
from pydantic import Field

from .jobs import JOBS
from .router import Router

INSTRUCTIONS = """OpenPeopleRouter finds and enriches people and companies through the provider accounts its owner configured.
Use a job tool first (find_people, enrich_person, find_contact, verify_email, find_companies, enrich_company, read_profile): it picks a configured provider, falls back to the next on a miss, and returns rows in one shape with the provider named on each.
When no job fits, search_operations finds a provider operation by words, describe_operation shows its parameters, and call_operation runs it and returns the provider's own response.
providers shows what is configured. Calls are billed by each provider to the owner's account."""

COMMON = {
    "providers": (list[str] | None, "only these providers, by id, in this order of preference"),
    "raw": (bool, "include each provider's full record in `raw`"),
}


def _job_tool(router: Router, name: str) -> Tool:
    job = JOBS[name]

    async def run(**kwargs: Any) -> dict:
        providers = kwargs.pop("providers", None)
        raw = bool(kwargs.pop("raw", False))
        given = {k: v for k, v in kwargs.items() if v not in (None, "")}
        return await router.run(name, given, providers=providers, raw=raw)

    params = []
    for field_name, about in job.inputs.items():
        kind = int if field_name == "limit" else str
        default = job.defaults.get(field_name)
        params.append(Parameter(field_name, Parameter.KEYWORD_ONLY, default=default,
                                annotation=Annotated[kind | None, Field(description=about)]))
    for field_name, (kind, about) in COMMON.items():
        params.append(Parameter(field_name, Parameter.KEYWORD_ONLY, default=None if kind is not bool else False,
                                annotation=Annotated[kind, Field(description=about)]))
    run.__signature__ = Signature(params, return_annotation=dict)
    run.__annotations__ = {p.name: p.annotation for p in params} | {"return": dict}
    run.__name__ = name
    return Tool.from_function(run, name=name, description=job.description)


def create_server(router: Router, auth=None) -> FastMCP:
    mcp = FastMCP("OpenPeopleRouter", instructions=INSTRUCTIONS, auth=auth)
    catalog = router.catalog

    for name in JOBS:
        mcp.add_tool(_job_tool(router, name))

    @mcp.tool
    async def providers(configured_only: bool = False) -> dict:
        """Providers in the catalog: which have keys here, the variable each one reads, and the jobs it serves."""
        rows = []
        for p in catalog.providers.values():
            ready = router.configured(p.id)
            if configured_only and not ready:
                continue
            jobs = sorted({r.job for op in p.operations.values() for r in op.routes})
            rows.append({"id": p.id, "title": p.title, "configured": ready, "key": p.key.envs(),
                         "jobs": jobs, "operations": len(p.operations), "site": p.site})
        return {"providers": rows}

    @mcp.tool
    async def search_operations(
        query: str,
        configured_only: bool = False,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict:
        """Find provider operations by words ('instagram followers', 'github user', 'company technographics'). Searches the catalog, not people."""
        keep = (lambda op: router.configured(op.provider)) if configured_only else (lambda op: True)
        found = catalog.search(query, limit=limit, keep=keep)
        return {"operations": [{**op.view(), "configured": router.configured(op.provider)} for op in found]}

    @mcp.tool
    async def describe_operation(operation: str) -> dict:
        """Parameters, price and documentation of one operation, by the id search_operations returned."""
        op = catalog.operations.get(operation)
        if op is None:
            return {"error": "unknown operation"}
        provider = catalog.providers[op.provider]
        return {**op.view(full=True), "provider": provider.title, "configured": router.configured(op.provider),
                "key": provider.key.envs()}

    @mcp.tool
    async def call_operation(operation: str, params: dict | None = None) -> dict:
        """Run one operation with its own parameter names and return the provider's response as it came. The provider may charge for it."""
        return await router.call(operation, params or {})

    return mcp
