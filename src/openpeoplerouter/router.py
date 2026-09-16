"""BYOK routing. No customer accounts, credit conversion or payment gateway."""
from __future__ import annotations

import json
from typing import Any

from fastmcp import Client
from .catalog.plan import candidates_for
from .catalog.relay import Relay
from .catalog.store import Catalog
from .errors import error_view


class Router:
    def __init__(self, catalog: Catalog, credentials: dict[str, str], transport=None):
        self.catalog = catalog
        self.credentials = credentials
        self.relay = Relay(catalog, credentials=credentials, transport=transport)
        self.enabled = {s.strip() for s in credentials.get('OPENPEOPLEROUTER_PROVIDERS', '').split(',') if s.strip()}

    def redact(self, value):
        names = {v.auth.credential for v in self.catalog.vendors.values()} | {'DINQ_API_KEY'}
        secrets = [self.credentials[n] for n in names if self.credentials.get(n)]
        def walk(item):
            if isinstance(item, dict):
                return {key: walk(val) for key, val in item.items()}
            if isinstance(item, list):
                return [walk(val) for val in item]
            if isinstance(item, str):
                for secret in secrets:
                    item = item.replace(secret, '[redacted]')
                return item
            return item
        return walk(value)

    def available(self, vendor: str) -> bool:
        if self.enabled and vendor not in self.enabled:
            return False
        if vendor == 'dinq':
            return bool(self.credentials.get('DINQ_API_KEY'))
        return self.catalog.credential_present(vendor, self.credentials)

    async def dinq(self, capability: str, args: dict[str, Any]) -> dict:
        """Explicit optional paid provider, using the public DINQ MCP interface."""
        try:
            async with Client('https://router.dinq.me/test', auth=self.credentials['DINQ_API_KEY'], timeout=120) as client:
                result = await client.call_tool(capability.replace('.', '_'), args)
                doc = result.data
                if not isinstance(doc, dict):
                    doc = next((json.loads(c.text) for c in result.content if getattr(c, 'type', '') == 'text'), {})
                if not isinstance(doc, dict):
                    raise ValueError('invalid provider response')
                if result.is_error:
                    return {'outcome': 'error', 'error': error_view('provider_error', 'DINQ rejected the request')}
                # DINQ may charge its own account. The open router has no credit system.
                return {'capability': capability, 'outcome': doc.get('outcome', 'hit'),
                        'output': doc.get('output'), 'raw': doc, '_meta': {'provider': 'dinq'}}
        except Exception:
            return {'outcome': 'error', 'error': error_view('provider_error', 'DINQ unavailable; check its key, plan and connectivity')}

    async def _run(self, capability: str, supplied: dict, options: dict | None = None) -> dict:
        options = options or {}
        pin = options.get('vendor')
        if pin == 'dinq':
            if not self.available('dinq'):
                return {'outcome': 'error', 'error': error_view('missing_credential', 'Configure DINQ_API_KEY and enable dinq')}
            return await self.dinq(capability, supplied)
        plan = candidates_for(self.catalog, capability, supplied, env=self.credentials,
                              exclude={v for v in self.catalog.vendors if not self.available(v)})
        if plan.contract is None or plan.variant is None:
            return {'outcome': 'needs_identifier', 'error': error_view('bad_input', 'Supply identifiers accepted by this capability')}
        candidates = [c for c in plan.candidates if not pin or pin in (c.endpoint.id, c.endpoint.vendor)]
        attempts, merged = [], []
        last_output = None
        for c in candidates:
            raw, attempt = await self.relay.run(c, plan.identity)
            output = None
            if attempt.outcome == 'hit':
                try:
                    output = c.adapter.from_upstream(raw)
                    if plan.contract.is_miss(output):
                        attempt.outcome = 'miss'
                except Exception:
                    attempt.outcome = 'error'
                    attempt.error = error_view('provider_error', 'Provider response does not match its adapter')
            attempts.append(attempt.view())
            if attempt.outcome == 'hit':
                last_output = output
                if plan.contract.merge:
                    seen = {json.dumps(r, sort_keys=True, default=str) for r in merged}
                    for row in output.get(plan.contract.merge, []):
                        key = json.dumps(row, sort_keys=True, default=str)
                        if key not in seen:
                            merged.append(row)
                            seen.add(key)
                else:
                    return {'capability': capability, 'outcome': 'hit', 'output': output, 'raw': raw,
                            '_meta': {'tried': attempts}}
            if options.get('waterfall') is False:
                break
        if last_output is not None:
            if plan.contract.merge:
                last_output[plan.contract.merge] = merged
            return {'capability': capability, 'outcome': 'hit', 'output': last_output, '_meta': {'tried': attempts}}
        # DINQ is only invoked when explicitly selected, avoiding surprise paid fallback.
        outcome = 'miss' if attempts and all(a['outcome'] == 'miss' for a in attempts) else 'error'
        return {'capability': capability, 'outcome': outcome, '_meta': {'tried': attempts},
                'error': None if outcome == 'miss' else error_view('missing_credential' if not attempts else 'provider_error',
                    'No configured provider could answer. Inspect capabilities or find_tool; DINQ is optional with vendor="dinq".')}

    async def _call(self, endpoint_id: str, args: dict) -> dict:
        ep = self.catalog.by_id.get(endpoint_id)
        if not ep or not ep.live:
            return {'outcome': 'error', 'error': error_view('bad_input', 'Unknown or disabled endpoint')}
        if not self.available(ep.vendor):
            return {'outcome': 'error', 'error': error_view('missing_credential', 'Provider not configured or disabled')}
        raw, attempt = await self.relay.call(ep, args)
        return {'outcome': attempt.outcome, 'raw': raw, '_meta': {'tried': [attempt.view()]}}

    async def run(self, capability: str, supplied: dict, options: dict | None = None) -> dict:
        return self.redact(await self._run(capability, supplied, options))

    async def call(self, endpoint_id: str, args: dict) -> dict:
        return self.redact(await self._call(endpoint_id, args))
