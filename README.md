# OpenPeopleRouter

**One MCP interface for people discovery. Bring your own provider accounts.**

Find candidates, researchers, creators, industry experts and business contacts;
enrich profiles and companies; resolve identities and discover contact details.
Use unified capability tools first, then search the provider endpoint catalog
when you need a platform-specific API.

This is an independent, self-hosted project. It has no DINQ login requirement,
customer database, credit wallet, markup, payment gateway or hosted deployment
dependency. You supply provider API keys and pay the providers directly.
DINQ is an optional hosted provider, like a separate paid account you can choose.

[中文说明](README.zh-CN.md) · [Provider configuration](docs/providers.md) · [Architecture](docs/architecture.md)

## Run locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).
From your checkout:

```bash
uv sync
cp .env.example .env
# Edit .env locally: add only the provider keys you want to use.
uv run openpeoplerouter providers
uv run openpeoplerouter check
uv run openpeoplerouter serve
```

The default transport is MCP stdio. It waits for an MCP client and is not an
interactive chat prompt. Environment variables override `.env` values.

For an MCP client supporting command-based servers, use this configuration with
the absolute path to your checkout and your installed `uv` executable:

```json
{
  "mcpServers": {
    "openpeoplerouter": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/openpeoplerouter", "run", "openpeoplerouter", "serve"]
    }
  }
}
```

This is a generic MCP configuration example; individual clients can use different
configuration formats. No provider key needs to be pasted into a conversation.

## Tools

| Tool | Purpose |
| --- | --- |
| `people_search` | Find people by criteria or source URL |
| `people_enrich` | Enrich a known person's profile |
| `companies_search` | Find companies |
| `companies_enrich` | Enrich a company's profile |
| `social_profile` | Read social account profiles |
| `people_identity_resolve` | Resolve identities across platforms |
| `people_from_image` | Discover image sources |
| `people_contact_find` | Find or verify contact details |
| `capabilities` | Inspect coverage and available providers |
| `find_tool` | Discover endpoints when unified capabilities are insufficient |
| `endpoint` | Inspect arguments and provider documentation |
| `call_tool` | Execute a provider endpoint with your own credentials |

The initial catalog contains 29 direct HTTP providers and 1,641 endpoint
definitions. **Definitions do not mean every API is enabled, tested, free or
available on your plan.** Unified routing needs both a configured provider and a
matching adapter. Some capabilities require DINQ or another custom provider
adapter. Use `capabilities` and `find_tool` to inspect availability.

## Provider control

```dotenv
# Optional allowlist: only these providers may be called.
OPENPEOPLEROUTER_PROVIDERS=hunter,tikhub,openalex
HUNTER_API_KEY=your-own-key
TIKHUB_API_KEY=your-own-key
```

Set `vendor` on a unified call to select one provider or endpoint. Set
`waterfall=false` to try only the first eligible endpoint. The default can call
multiple providers on misses/errors; merging capabilities can call multiple
providers even after a hit. Provider charges may apply to each request.
There is no central credit budget or automatic invoice reconciliation.
Catalog pricing is informational, may be outdated and may differ from your plan.

### Optional DINQ provider

```dotenv
DINQ_API_KEY=your-own-dinq-key
# Include dinq if you use an allowlist:
OPENPEOPLEROUTER_PROVIDERS=dinq,hunter
```

Select `vendor="dinq"` in a unified tool call. This sends the request to the
public hosted PeopleRouter MCP at `https://router.dinq.me/test` using your DINQ
API key. DINQ's own plan and charges apply. It is never selected automatically,
and other providers work without a DINQ account. The bridge has protocol tests;
no paid DINQ request is made during installation or CI.

## HTTP / Docker

```bash
# In .env, set OPENPEOPLEROUTER_TOKEN to a long random secret first.
uv run openpeoplerouter serve --transport http --host 0.0.0.0
# Or:
docker compose up --build -d
```

MCP endpoint: `http://127.0.0.1:8093/mcp`. Supply
`Authorization: Bearer <OPENPEOPLEROUTER_TOKEN>` when enabled. Docker publishes
only to localhost by default. Use your own TLS reverse proxy for remote access.
This is a single-owner instance: clients share the configured provider keys.
It does not implement per-user accounts or OAuth. Public binding requires a token.

## Develop

```bash
uv run pytest -q
uv build
```

Tests use synthetic responses and in-process MCP clients. They do not spend
provider credits. The catalog ships inside the Python package, so installation
has no dependency on a sibling repository or the original private project.

To add a provider, see [the provider guide](docs/providers.md).

## Related open-source projects

**[OpenMailConnect](https://github.com/DINQ-labs/openmailconnect)** — a standalone,
self-hosted MCP server for Gmail and SMTP, maintained by DINQ Labs under Apache-2.0.
It provides Gmail search, reading, threads, drafts and sending, plus SMTP sending.
Use OpenPeopleRouter to discover people and OpenMailConnect to work with your own
mailbox; both can be configured independently in the same MCP client.

OpenMailConnect is optional and is not bundled with OpenPeopleRouter. Follow its
[installation guide](https://github.com/DINQ-labs/openmailconnect#install) to set up
your own Gmail OAuth application or SMTP credentials. It requires no DINQ account
or PeopleRouter credits. Sending email requires the user's authorization.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Catalog portions originate
from the Apache-2.0-licensed treg project; attribution is retained. Provider
services, datasets and subscriptions are governed by their own terms, not by
this software license.
