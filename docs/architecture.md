# Independent open-source boundary

Client → MCP tools → unified contract → configured provider/adapter → provider API.
When the contract cannot meet the need: find_tool → endpoint → call_tool.

Only catalog models, transformations, public HTTP request machinery and provider
metadata were extracted from PeopleRouter. The open router and entry point have
no imports from the original project. Runtime data is packaged into the wheel.
There are no symlinks, private package requirements or requests to the commercial
account/payment gateway. No customer rows, production environment files, example
responses, Git history, deployment credentials or internal service URLs are copied.

The optional DINQ bridge calls its public MCP service only when the caller pins
vendor=dinq. The open project does not impose its own credits or account login.
It is a client of that supplier, not a replacement for its commercial API.

No PostgreSQL, analytics storage, user administration or commercial frontend is
included. Configuration is local environment variables/.env. HTTP authentication
is an owner-managed bearer token; stdio relies on local process access. This
initial release targets single-owner installations, not multi-tenant hosting.

The inherited provider catalog requires ongoing maintenance. The five entries
that required the private internal DINQ service were deliberately excluded rather
than advertised as direct integrations. Existing supplier-native credit units in
catalog metadata describe their published billing, not a router credit wallet.
