# How routing works

```
MCP client ──► job tool (find_contact …) ──► router ──► provider operation ──► provider API
           └─► search_operations / describe_operation / call_operation ─────┘
```

**Catalog.** `catalog.py` loads every file in `providers/`. `openpeoplerouter check`
validates them: https base URLs, path placeholders, param locations and types,
that every route sends the inputs it needs and fills every required param, and that
every JMESPath expression compiles.

**Jobs.** `jobs.py` defines the seven jobs: their inputs and the fields each answer
carries. Before routing, the router derives what follows from the inputs — first and
last name from a full name, a bare domain from a URL, platform and handle from a
profile URL — so a provider that needs `first_name` can serve a caller who gave
`full_name`.

**Candidates.** A route is a candidate when its provider is configured (its key is
set, or it needs none, and it is allowed by `OPENPEOPLEROUTER_PROVIDERS`) and one of
its `needs` sets is satisfied. `find_people` routes also match on `audience`, and
`read_profile` routes on `platform`.

**Order.** Providers named in `OPENPEOPLEROUTER_ORDER` (or the call's `providers`)
first, then routes marked with a higher `priority`, then by price: free, then cheapest
known, then unknown. At most three are
tried per call.

**Answers.** One-record jobs stop at the first provider that returns something.
List jobs keep going until `limit` rows are collected, merging rows that share a
LinkedIn URL, profile URL, email, domain, or name with employer; a merged row lists
the other providers in `also_from`.

**Outcomes.** Each attempt is `ok`, `empty` (a miss: a not-found status, a
`no_match` error body, or a reply with no rows) or `failed` with a code —
`missing_key`, `key_rejected`, `out_of_credit`, `rate_limited`, `bad_request`,
`timeout`, `network`, `provider_error`. A miss moves on to the next provider; so
does a failure.

**Asynchronous providers.** A route with `poll` sends the request, then asks the
result operation every `every` seconds until `until` holds or `within` seconds pass.

**Secrets.** Keys are read from the environment (or `.env`) and only ever placed in
the request to their own provider. Every value returned to the client is scrubbed of
all configured keys.

**Direct calls.** `call_operation` checks the arguments against the operation's
params, sends them as given and returns the provider's response untouched. It is the
way to reach the two thousand operations that no job covers.
