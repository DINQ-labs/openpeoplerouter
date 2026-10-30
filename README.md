# OpenPeopleRouter

**An open-source MCP server that finds people and companies through the data
providers you already pay for.** Bring your own keys; nothing goes through a
middleman.

- **7 job tools** an agent can call without knowing any provider: `find_people`,
  `enrich_person`, `find_contact`, `verify_email`, `find_companies`,
  `enrich_company`, `read_profile`.
- **68 providers, 2,200+ operations** — B2B people and company data, email
  finding and verification, phone data, research and developer profiles, social
  platforms, web search and scraping. See [docs/providers.md](docs/providers.md).
- **Your keys, your bills.** Each provider bills your own account. Keys stay in
  your environment and are scrubbed from every response.
- **One YAML file per provider.** Adding one needs no Python.

[中文说明](README.zh-CN.md) · [Provider list](docs/providers.md) · [Provider file format](docs/provider-format.md) · [How routing works](docs/architecture.md)

## Run it

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/DINQ-labs/openpeoplerouter && cd openpeoplerouter
uv sync
cp .env.example .env          # fill in only the providers you use
uv run openpeoplerouter providers
uv run openpeoplerouter run find_contact "full_name=Jane Doe" company_domain=example.com
```

Several sources work with no key at all (OpenAlex, ORCID, Crossref, Wikidata,
GitHub, Hugging Face, Semantic Scholar, Stack Exchange, Bluesky), so the server is
useful before you configure anything.

### In an MCP client

The default transport is stdio:

```json
{
  "mcpServers": {
    "openpeoplerouter": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/openpeoplerouter", "run", "openpeoplerouter", "serve"]
    }
  }
}
```

Over HTTP, for a server you share with your own tools:

```bash
OPENPEOPLEROUTER_TOKEN=change-me uv run openpeoplerouter serve --transport http --host 0.0.0.0 --port 8080
```

Clients then connect to `http://host:8080/mcp` with `Authorization: Bearer change-me`.
The server refuses to listen beyond localhost without a token, because it spends
your provider credits. `docker compose up` does the same in a container.

## Tools

| Tool | What it does |
| --- | --- |
| `find_people` | People by title, employer, place, skills or a description. `audience` picks professionals (default), researchers, developers or creators. Rows from several providers are merged and de-duplicated. |
| `enrich_person` | One person from an email, LinkedIn URL, phone, or name with employer. |
| `find_contact` | Work email and phone for one person. |
| `verify_email` | Whether an address can receive mail. |
| `find_companies` | Companies by industry, place, size, technology or a description. |
| `enrich_company` | One company from its domain, name or LinkedIn page. |
| `read_profile` | One public profile on LinkedIn, X, Instagram, TikTok, YouTube, GitHub, Bluesky, Threads and more. |
| `providers` | What is configured, and which variable each provider reads. |
| `search_operations` | Find any provider operation by words. |
| `describe_operation` | Its parameters, price and docs. |
| `call_operation` | Run it with the provider's own parameters and get the raw response. |

Every job result lists what was `tried`: the operation, whether it answered, how
long it took, and the error if it failed — so an agent can tell "nobody matched"
from "the key was rejected" from "out of credit".

## Choosing providers

```dotenv
# Only these providers may be called (default: every provider with a key, plus keyless ones)
OPENPEOPLEROUTER_PROVIDERS=hunter,apollo,openalex
# Try these first, in this order; the rest follow, cheapest first
OPENPEOPLEROUTER_ORDER=apollo,hunter
```

A job call can also pass `providers: ["pdl", "lusha"]` to use only those, in that
order, and `raw: true` to get each provider's full record next to the mapped
fields.

## Command line

```bash
openpeoplerouter serve [--transport stdio|http] [--host] [--port]
openpeoplerouter providers [--markdown]
openpeoplerouter check                     # validate every provider file
openpeoplerouter run <job> key=value ...    # run a job once
openpeoplerouter call <provider.operation> key=value ...
```

Values that parse as JSON are sent as JSON (`limit=5`, `filters='{"x":1}'`).

## Adding a provider

Write `src/openpeoplerouter/providers/<id>.yaml` as described in
[docs/provider-format.md](docs/provider-format.md). For APIs with an OpenAPI
document, `scripts/from_openapi.py` drafts the operations. Run
`openpeoplerouter check` and `uv run pytest`, then open a pull request.

Provider definitions describe each provider's public API documentation. Most
routes were checked against those documents and response schemas; keyless and
test-key providers were also called live. If a provider changed its API, the
fix is usually one line in its file.

## Responsible use

You are responsible for using each provider within its terms and the law where
you and the people you look up are, including data-protection rules such as the
GDPR and CCPA. Some providers carry their own restrictions (for example, phone
data that is not a consumer report and must not be used for credit, insurance,
employment or housing decisions).

## License

Apache-2.0
