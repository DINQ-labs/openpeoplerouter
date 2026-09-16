"""MCP interface: unified capabilities first, endpoint discovery as fallback."""
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.tools import Tool
from pydantic import Field

from .catalog.tools import capability_tools
from .router import Router

INSTRUCTIONS = """OpenPeopleRouter connects your own provider accounts for recruiting, research collaboration, creator partnerships, expert interviews and business contact discovery across professional, research and social platforms.
Use the matching unified capability tool first. Only when unified capabilities cannot meet the request, use find_tool to discover another endpoint, inspect it with endpoint, then execute it with call_tool. Catalog entries are not necessarily configured: capabilities and find_tool show availability. Provider subscriptions and API charges are paid directly to the providers. DINQ is optional and must be explicitly selected with vendor='dinq'."""


def create_server(router: Router, auth=None):
    mcp = FastMCP('OpenPeopleRouter', instructions=INSTRUCTIONS, auth=auth)

    @mcp.tool
    async def capabilities() -> dict:
        """List unified capabilities, inputs and configured providers. No provider request."""
        rows = []
        for name in router.catalog.jobs():
            row = router.catalog.capability_view(name, router.credentials)
            row['vendors'] = [v for v in row['vendors'] if router.available(v)]
            row['dinq_available'] = router.available('dinq')
            rows.append(row)
        return {'capabilities': rows}

    for name, description, fn in capability_tools(router.catalog, router.run):
        mcp.add_tool(Tool.from_function(fn, name=name, description=description))

    @mcp.tool
    async def find_tool(query: str, limit: Annotated[int, Field(ge=1, le=40)] = 10) -> dict:
        """Find provider endpoints when unified capabilities cannot meet the need. Searches API metadata, not people."""
        rows = router.catalog.search(query, limit=limit)
        return {'tools': [{**ep.view(usd=router.catalog.usd(ep)), 'configured': router.available(ep.vendor)} for ep in rows]}

    @mcp.tool
    async def endpoint(endpoint_id: str) -> dict:
        """Inspect an endpoint's arguments, provider documentation and availability before calling it."""
        ep = router.catalog.by_id.get(endpoint_id)
        if not ep:
            return {'error': 'unknown endpoint'}
        return {**ep.view(usd=router.catalog.usd(ep), full=True), 'configured': router.available(ep.vendor)}

    @mcp.tool
    async def call_tool(endpoint_id: str, args: dict | None = None) -> dict:
        """Execute a discovered endpoint using your provider key. Provider charges may apply."""
        return await router.call(endpoint_id, args or {})

    return mcp
