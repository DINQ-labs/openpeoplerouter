"""Command line: serve the MCP server, list providers, check the catalog, try an operation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from dotenv import dotenv_values

from .catalog import Catalog
from .router import Router


def _env(path: str) -> dict[str, str]:
    values = {k: v for k, v in dotenv_values(path).items() if v is not None} if os.path.exists(path) else {}
    return {**values, **os.environ}


def main() -> None:
    parser = argparse.ArgumentParser(prog="openpeoplerouter", description="People and company data through your own provider keys")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the MCP server (default)")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    listing = sub.add_parser("providers", help="list providers and whether their keys are set")
    listing.add_argument("--markdown", action="store_true", help="print the table in docs/providers.md")
    check = sub.add_parser("check", help="validate every provider file")
    trial = sub.add_parser("call", help="run one operation: call hunter.email-finder domain=stripe.com full_name='Jane Doe'")
    trial.add_argument("operation")
    trial.add_argument("params", nargs="*")
    job = sub.add_parser("run", help="run one job: run find_contact full_name='Jane Doe' company_domain=stripe.com")
    job.add_argument("job")
    job.add_argument("inputs", nargs="*")
    for p in (serve, listing, check, trial, job):
        p.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    env = _env(getattr(args, "env_file", ".env"))
    catalog = Catalog.load(env.get("OPENPEOPLEROUTER_PROVIDER_DIR"))
    router = Router(catalog, env)
    command = args.command or "serve"

    if command == "check":
        problems = catalog.problems()
        print(json.dumps({"providers": len(catalog.providers), "operations": len(catalog.operations),
                          "routed": sum(1 for op in catalog.operations.values() if op.routes),
                          "problems": problems}, indent=2))
        raise SystemExit(1 if problems else 0)
    if command == "providers":
        if args.markdown:
            print(_markdown(catalog))
            return
        for p in catalog.providers.values():
            jobs = sorted({r.job for op in p.operations.values() for r in op.routes})
            mark = "✓" if router.configured(p.id) else " "
            print(f"{mark} {p.id:<18} {', '.join(p.key.envs()) or '(no key)':<34} {', '.join(jobs)}")
        return
    if command in ("call", "run"):
        pairs = dict(item.split("=", 1) for item in (args.params if command == "call" else args.inputs))
        values = {k: _value(v) for k, v in pairs.items()}
        coro = router.call(args.operation, values) if command == "call" else router.run(args.job, values, raw=True)
        print(json.dumps(asyncio.run(coro), indent=2, ensure_ascii=False, default=str))
        return

    from .server import create_server

    auth = None
    token = env.get("OPENPEOPLEROUTER_TOKEN")
    transport = getattr(args, "transport", "stdio")
    if transport == "http":
        if args.host not in ("127.0.0.1", "localhost", "::1") and not token:
            parser.error("set OPENPEOPLEROUTER_TOKEN before serving your provider keys beyond localhost")
        if token:
            from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

            auth = StaticTokenVerifier(tokens={token: {"client_id": "owner", "scopes": []}})
    mcp = create_server(router, auth)
    if transport == "stdio":
        mcp.run(transport="stdio", show_banner=False)
    else:
        mcp.run(transport="http", host=args.host, port=args.port, path="/mcp", show_banner=False)


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def _markdown(catalog: Catalog) -> str:
    lines = ["| Provider | Key variable | Jobs | Operations | Docs |", "| --- | --- | --- | --- | --- |"]
    for p in sorted(catalog.providers.values(), key=lambda p: p.title.lower()):
        jobs = ", ".join(sorted({r.job for op in p.operations.values() for r in op.routes})) or "—"
        key = ", ".join(f"`{e}`" for e in p.key.envs()) or "none"
        lines.append(f"| [{p.title}]({p.site or p.docs}) | {key} | {jobs} | {len(p.operations)} | [docs]({p.docs}) |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
