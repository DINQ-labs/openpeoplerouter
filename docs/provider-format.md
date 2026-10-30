# Provider file format

Each provider is one YAML file in `src/openpeoplerouter/providers/`. Nothing else
needs to change to add one: drop the file in, run `openpeoplerouter check`, open a
pull request.

```yaml
id: hunter                       # file name without .yaml; lowercase, no spaces
title: Hunter
about: One line on what this provider is good for.
site: https://hunter.io
docs: https://hunter.io/api-documentation/v2
pricing: https://hunter.io/pricing
api: https://api.hunter.io/v2    # base URL, https only
credit_usd: 0.0245               # optional: what one provider credit costs on its entry plan
key:
  env: HUNTER_API_KEY            # the variable the user sets
  header: X-API-KEY              # where the key goes (one of the forms below)
operations:
  email-finder:                  # operation id; called as hunter.email-finder
    title: Work email from a name and company
    about: Anything an agent should know before calling it.
    request: GET /email-finder
    docs: https://hunter.io/api-documentation/v2#email-finder
    params:
      domain: {about: company domain}
      full_name: {}
      max_duration: {type: integer, about: seconds, 3-20}
    price: {credits: 1, per: success}
    jobs:
      find_contact:
        needs: [[full_name, company_domain]]
        send: {full_name: full_name, company_domain: domain}
        result: data
        fields: {email: email, confidence: score}
```

## `key`

| Form | Sends |
| --- | --- |
| `header: X-Api-Key` | `X-Api-Key: <key>` |
| `header: Authorization` + `prefix: 'Basic '` | `Authorization: Basic <key>` |
| `bearer: true` | `Authorization: Bearer <key>` |
| `query: api_key` | `?api_key=<key>` |
| `basic: user` / `basic: password` | HTTP Basic with the key as user or password |
| `body: apiKey` | `{"apiKey": "<key>"}` in JSON bodies, `?apiKey=` on GET |
| `also: [{header: X-Secret, env: VENDOR_SECRET}]` | a second header from a second variable |
| `optional: true` | the API works without a key; the key raises limits |
| `key: {}` | no key at all |

## `params`

Each param has `in` (`query` default, `body`, `path`, `header`, `form`), `type`
(`string` default, `integer`, `number`, `boolean`, `array`, `object`),
`required`, `default`, `choices` and `about`. A path param must appear in the
request as `{name}`.

Query params whose names end in `[]` (`person_titles[]`) repeat the key for each
value; other list values are sent comma-separated.

Operation-level options:

- `body: form` sends form fields instead of JSON; `body: whole` sends the one body
  param as the entire JSON body (for APIs whose body is a free-form object).
- `api:` an operation on another host of the same provider.
- `not_found: 404` (or a list) — statuses that mean nobody matched. Not an error;
  the router moves to the next provider.
- `no_match: "error_code == 'NO_MATCH'"` — the same for providers that report "no
  match" in an error body.

## `price`

`{usd: 0.01, per: call}`, `{credits: 1, per: success}` or `{usd: 0, per: call}` for
free. `per` is `call` (billed whatever happens), `success` (billed only when
something is found) or `result` (billed per row). `note` explains anything else.
Prices only order providers; the provider's own bill is the truth.

## `jobs`

A route makes an operation answer one of the jobs in
[`jobs.py`](../src/openpeoplerouter/jobs.py). Operations without routes are still
reachable through `search_operations` and `call_operation`.

- `needs` — sets of job inputs, any one of which is enough to call this operation.
  Inputs derived by the router count too: `first_name`/`last_name` from
  `full_name`, `linkedin_handle` from `linkedin_url`, `platform`/`handle` from a
  profile `url`.
- `send` — job input → param. A dotted target (`data.0.email`) builds nested JSON;
  a target ending in `[]` wraps a single value in a list. `{to: param, as: template}`
  puts the value inside a structure, with `$` marking where it goes:
  `{to: filters.titles, as: [{value: $, exclude: false}]}`. A string template
  (`as: "location:$"`) appends to the param, so several inputs build one query.
- `fixed` — constant params, applied first.
- `limit` — the param that sets how many rows come back.
- `result` — [JMESPath](https://jmespath.org) to the record, or to the list of rows.
- `fields` — job field → JMESPath within the record. `split(text, sep)` and
  `lower(text)` are available besides the standard functions.
- `poll` — for providers that answer later:
  `{operation: result-op, send: {id: id}, until: "status == 'done'", every: 2, within: 60}`.
  `send` takes values from the first reply; `when` (optional) polls only if true
  for the first reply.
- `priority` — a higher number is tried first among routes of the same job (default 0).
- `audience` — `find_people` only: `professionals` (default), `researchers`,
  `developers`, `creators`, or `any`.
- `platform` — `read_profile` only: the platform this operation reads.

## Drafting from OpenAPI

```bash
uv run python scripts/from_openapi.py https://api.example.com/openapi.json --only /v1/people > draft.yaml
```

prints the `operations:` block from a provider's published OpenAPI document. Add
the header, key, prices and routes by hand, then run `openpeoplerouter check`.
