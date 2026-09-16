"""Local stdio by default; optional protected HTTP deployment."""
import argparse
import json
import os

from dotenv import dotenv_values
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from .catalog.store import load_catalog
from .router import Router
from .server import create_server


def main():
    parser = argparse.ArgumentParser(description='OpenPeopleRouter — bring your own provider keys')
    parser.add_argument('command', choices=['serve', 'providers', 'check'], nargs='?', default='serve')
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8093)
    args = parser.parse_args()
    env = {**{k: v for k, v in dotenv_values(args.env_file).items() if v is not None}, **os.environ}
    catalog = load_catalog(env.get('OPENPEOPLEROUTER_CATALOG_DIR'))
    router = Router(catalog, env)
    if args.command == 'providers':
        rows = [{'provider': v.id, 'key_variable': v.auth.credential, 'configured': router.available(v.id)} for v in catalog.vendors.values()]
        rows.append({'provider': 'dinq', 'key_variable': 'DINQ_API_KEY', 'configured': router.available('dinq')})
        print(json.dumps(rows, indent=2))
        return
    if args.command == 'check':
        print(json.dumps({'providers': len(catalog.vendors), 'endpoints': len(catalog.endpoints), 'capabilities': len(catalog.contracts), 'problems': catalog.problems}, indent=2))
        raise SystemExit(bool(catalog.problems))
    token = env.get('OPENPEOPLEROUTER_TOKEN')
    if args.transport == 'http' and args.host not in ('127.0.0.1', 'localhost', '::1') and not token:
        parser.error('Set OPENPEOPLEROUTER_TOKEN before exposing shared provider keys over HTTP')
    auth = StaticTokenVerifier(tokens={token: {'client_id': 'self-hosted', 'scopes': []}}) if args.transport == 'http' and token else None
    mcp = create_server(router, auth)
    if args.transport == 'stdio':
        mcp.run(transport='stdio', show_banner=False)
    else:
        mcp.run(transport='http', host=args.host, port=args.port, path='/mcp', show_banner=False)


if __name__ == '__main__':
    main()
