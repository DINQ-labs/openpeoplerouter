# Configure and extend providers

`openpeoplerouter providers` lists provider IDs, environment variable names and
configuration status without printing credentials. `.env.example` lists the
supported key variables. Configure keys locally, then restart the MCP process.

Use `OPENPEOPLEROUTER_PROVIDERS` as a comma-separated allowlist. Empty means all
configured providers, including catalog entries that do not require keys.
A provider key being present is not proof of a valid subscription.

To add a provider, copy the packaged `src/openpeoplerouter/data` directory to a
user-owned directory and set `OPENPEOPLEROUTER_CATALOG_DIR` to its absolute path.
The custom directory replaces the bundled catalog; keep contracts, adapters,
capabilities and fx files alongside vendors. Run `openpeoplerouter check`.

A provider YAML defines `vendor`, `name`, `base_url`, `auth` and `endpoints`.
Use an HTTPS base URL, and reference an environment variable via
`auth.credential`; do not store a literal secret. Each endpoint defines an ID,
capability, HTTP method/path and argument schema. An entry in adapters.yaml maps
unified inputs into provider request fields and normalizes response fields.
Without an adapter the endpoint remains discoverable through find_tool/call_tool.

Keep endpoint definitions and adapters covered with synthetic fixtures. Do not
commit real customer profiles, captured responses, private prices or credentials.
Provider charges, per-plan restrictions and API changes are independent of the
router. Do not mark availability as verified solely because a key exists.
