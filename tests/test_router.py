import json
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from openpeoplerouter.catalog import Catalog
from openpeoplerouter.jobs import JOBS, derive
from openpeoplerouter.router import Router
from openpeoplerouter.server import create_server

PROVIDERS = """
id: alpha
title: Alpha
docs: https://alpha.example/docs
api: https://api.alpha.example/v1
key: {env: ALPHA_KEY, header: X-Api-Key}
operations:
  people:
    title: People search
    request: POST /people
    params:
      filters: {in: body, type: object}
      size: {in: body, type: integer}
    price: {usd: 0.01, per: call}
    jobs:
      find_people:
        needs: [[title]]
        send: {title: 'filters.titles[]', company_domain: filters.domain}
        limit: size
        result: hits
        fields: {name: full_name, title: role, linkedin_url: links.linkedin}
  email:
    title: Email finder
    request: GET /email/{domain}
    params:
      domain: {in: path, required: true}
      name: {}
    not_found: 404
    price: {usd: 0.02, per: success}
    jobs:
      find_contact:
        needs: [[full_name, company_domain]]
        send: {full_name: name, company_domain: domain}
        result: data
        fields: {email: address}
---
id: beta
title: Beta
docs: https://beta.example/docs
api: https://api.beta.example
key: {env: BETA_KEY, query: token}
operations:
  people:
    title: People
    request: GET /search
    params:
      role: {}
      n: {type: integer}
    price: {usd: 0.001, per: call}
    jobs:
      find_people:
        needs: [[title]]
        send: {title: role}
        limit: n
        result: people
        fields: {name: name, linkedin_url: linkedin}
  contact:
    title: Contact
    request: GET /contact
    params:
      full_name: {required: true}
      domain: {required: true}
    price: {usd: 0.05, per: call}
    jobs:
      find_contact:
        needs: [[full_name, company_domain]]
        send: {full_name: full_name, company_domain: domain}
        result: '@'
        fields: {email: email, phone: phone}
"""


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    for doc in PROVIDERS.split("\n---\n"):
        name = doc.split("id: ")[1].split("\n")[0]
        (tmp_path / f"{name}.yaml").write_text(doc)
    return Catalog.load(tmp_path)


def test_fixture_catalog_is_valid(catalog):
    assert catalog.problems() == []


def test_shipped_catalog_is_valid():
    shipped = Catalog.load()
    assert shipped.problems() == []
    assert len(shipped.providers) >= 3
    assert all(p.api.startswith("https://") for p in shipped.providers.values())


def test_problems_name_the_mistake(tmp_path):
    (tmp_path / "bad.yaml").write_text("""
id: bad
title: Bad
docs: https://bad.example
api: http://bad.example
key: {env: BAD_KEY}
operations:
  one:
    request: FETCH /x/{id}
    jobs:
      find_people:
        needs: [[nickname]]
        send: {nickname: q}
        result: '[[['
        fields: {name: name}
""")
    found = " | ".join(Catalog.load(tmp_path).problems())
    for part in ("https URL", "no header, query, basic or body", "FETCH", "{id}", "nickname", "not a param", "bad expression"):
        assert part in found


async def test_cheapest_configured_provider_first_and_rows_merge(catalog):
    seen = []

    def reply(request: httpx.Request):
        seen.append(request)
        if request.url.host == "api.beta.example":
            assert request.url.params["token"] == "beta-secret"
            assert request.url.params["n"] == "3"
            return httpx.Response(200, json={"people": [{"name": "Ada", "linkedin": "https://linkedin.com/in/ada"}]})
        assert request.headers["X-Api-Key"] == "alpha-secret"
        body = json.loads(request.content)
        assert body == {"filters": {"titles": ["CTO"], "domain": "acme.com"}, "size": 3}
        return httpx.Response(200, json={"hits": [
            {"full_name": "Ada", "role": "CTO", "links": {"linkedin": "https://www.linkedin.com/in/ada/"}},
            {"full_name": "Grace", "role": "CTO"},
        ]})

    router = Router(catalog, {"ALPHA_KEY": "alpha-secret", "BETA_KEY": "beta-secret"}, httpx.MockTransport(reply))
    result = await router.run("find_people", {"title": "CTO", "company_domain": "https://acme.com/", "limit": 3})
    assert [r.url.host for r in seen] == ["api.beta.example", "api.alpha.example"]
    assert result["state"] == "found"
    assert [r["name"] for r in result["rows"]] == ["Ada", "Grace"]
    assert result["rows"][0]["also_from"] == ["alpha"]
    assert result["rows"][0]["title"] == "CTO"


async def test_single_record_stops_at_first_answer_and_404_is_a_miss(catalog):
    seen = []

    def reply(request: httpx.Request):
        seen.append(request.url.host)
        if request.url.host == "api.alpha.example":
            assert request.url.path == "/v1/email/acme.com"
            return httpx.Response(404, json={"error": "no match"})
        return httpx.Response(200, json={"email": "ada@acme.com"})

    router = Router(catalog, {"ALPHA_KEY": "a-secret", "BETA_KEY": "b-secret"}, httpx.MockTransport(reply))
    result = await router.run("find_contact", {"full_name": "Ada Lovelace", "company_domain": "acme.com"})
    assert seen == ["api.alpha.example", "api.beta.example"]
    assert result["tried"][0]["state"] == "empty"
    assert result["record"] == {"provider": "beta", "email": "ada@acme.com"}


async def test_only_configured_providers_are_called_and_keys_never_leak(catalog):
    def reply(request: httpx.Request):
        return httpx.Response(401, json={"message": "bad key beta-secret-value"})

    router = Router(catalog, {"BETA_KEY": "beta-secret-value"}, httpx.MockTransport(reply))
    result = await router.run("find_contact", {"full_name": "Ada Lovelace", "company_domain": "acme.com"})
    assert [t["provider"] for t in result["tried"]] == ["beta"]
    assert result["state"] == "failed"
    assert result["tried"][0]["error"] == "key_rejected"
    assert "beta-secret-value" not in json.dumps(result)

    none = Router(catalog, {}, httpx.MockTransport(reply))
    result = await none.run("find_contact", {"full_name": "Ada Lovelace", "company_domain": "acme.com"})
    assert result["state"] == "no_provider"
    assert "ALPHA_KEY" in result["message"] and "BETA_KEY" in result["message"]


async def test_allow_list_and_order_from_environment(catalog):
    hosts = []

    def reply(request: httpx.Request):
        hosts.append(request.url.host)
        return httpx.Response(200, json={"people": [], "hits": []})

    env = {"ALPHA_KEY": "x" * 8, "BETA_KEY": "y" * 8, "OPENPEOPLEROUTER_ORDER": "alpha"}
    await Router(catalog, env, httpx.MockTransport(reply)).run("find_people", {"title": "CTO"})
    assert hosts == ["api.alpha.example", "api.beta.example"]
    hosts.clear()
    await Router(catalog, {**env, "OPENPEOPLEROUTER_PROVIDERS": "beta"}, httpx.MockTransport(reply)).run("find_people", {"title": "CTO"})
    assert hosts == ["api.beta.example"]


async def test_call_operation_checks_params_before_sending(catalog):
    sent = []
    router = Router(catalog, {"BETA_KEY": "secret-123"}, httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={"ok": 1})))
    assert (await router.call("beta.contact", {"full_name": "Ada"}))["error"] == "bad_request"
    assert (await router.call("beta.contact", {"nope": 1, "full_name": "A", "domain": "b"}))["error"] == "bad_request"
    assert (await router.call("beta.missing", {}))["error"] == "unknown_operation"
    done = await router.call("beta.contact", {"full_name": "Ada", "domain": "acme.com"})
    assert done["state"] == "ok" and done["data"] == {"ok": 1}
    assert len(sent) == 1


def test_derive_fills_names_domains_and_profiles():
    got = derive("find_contact", {"full_name": "Ada King Lovelace", "company_domain": "https://www.acme.com/about"})
    assert (got["first_name"], got["last_name"], got["company_domain"]) == ("Ada", "King Lovelace", "acme.com")
    got = derive("read_profile", {"url": "https://www.instagram.com/natgeo/"})
    assert (got["platform"], got["handle"]) == ("instagram", "natgeo")
    got = derive("read_profile", {"url": "https://www.linkedin.com/in/ada-l/"})
    assert (got["platform"], got["handle"]) == ("linkedin", "ada-l")


async def test_mcp_server_exposes_jobs_and_operation_tools(catalog):
    router = Router(catalog, {"BETA_KEY": "secret-123"},
                    httpx.MockTransport(lambda r: httpx.Response(200, json={"people": [{"name": "Ada"}]})))
    async with Client(create_server(router)) as client:
        names = {t.name for t in await client.list_tools()}
        assert set(JOBS) | {"providers", "search_operations", "describe_operation", "call_operation"} == names
        found = (await client.call_tool("find_people", {"title": "CTO", "limit": 1})).data
        assert found["rows"] == [{"provider": "beta", "name": "Ada"}]
        listed = (await client.call_tool("providers", {})).data["providers"]
        assert {p["id"]: p["configured"] for p in listed} == {"alpha": False, "beta": True}
        ops = (await client.call_tool("search_operations", {"query": "email finder"})).data["operations"]
        assert ops[0]["id"] == "alpha.email"
        described = (await client.call_tool("describe_operation", {"operation": "alpha.email"})).data
        assert described["params"]["domain"] == {"in": "path", "type": "string", "required": True}


async def test_an_asynchronous_provider_is_polled_until_its_answer_is_ready(tmp_path):
    (tmp_path / "slow.yaml").write_text("""
id: slow
title: Slow
docs: https://slow.example
api: https://api.slow.example
key: {env: SLOW_KEY, header: x-api-key}
operations:
  start:
    request: POST /find
    params:
      fullname: {in: body}
      company_domain: {in: body}
    jobs:
      find_contact:
        needs: [[full_name, company_domain]]
        send: {full_name: fullname, company_domain: company_domain}
        poll: {operation: result, send: {id: id}, until: "status == 'done'", every: 0.01, within: 1}
        result: '@'
        fields: {email: email}
  result:
    request: GET /find
    params:
      id: {required: true}
""")
    calls = []

    def reply(request: httpx.Request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job-1"})
        assert request.url.params["id"] == "job-1"
        done = calls.count("GET") >= 3
        return httpx.Response(200, json={"status": "done", "email": "ada@acme.com"} if done else {"status": "running"})

    catalog = Catalog.load(tmp_path)
    assert catalog.problems() == []
    router = Router(catalog, {"SLOW_KEY": "slow-secret"}, httpx.MockTransport(reply))
    result = await router.run("find_contact", {"full_name": "Ada Lovelace", "company_domain": "acme.com"})
    assert calls == ["POST", "GET", "GET", "GET"]
    assert result["record"] == {"provider": "slow", "email": "ada@acme.com"}


SAMPLES = {
    "query": "data engineer", "title": "CTO", "company": "Acme", "company_domain": "acme.com", "domain": "acme.com",
    "location": "Berlin", "country": "DE", "seniority": "director", "keywords": "python", "email": "ada@acme.com",
    "linkedin_url": "https://www.linkedin.com/in/ada-l", "full_name": "Ada Lovelace", "first_name": "Ada",
    "last_name": "Lovelace", "phone": "+12065550100", "name": "Acme", "industry": "software", "employees": "51-200",
    "technology": "react", "url": "https://www.instagram.com/natgeo/", "handle": "natgeo", "audience": "professionals",
}


async def test_every_route_in_the_catalog_builds_a_request_to_its_own_host():
    from urllib.parse import urlsplit

    from openpeoplerouter.router import Router as R

    shipped = Catalog.load()
    env = {e: "test-key-123456" for p in shipped.providers.values() for e in p.key.envs()}
    sent = []

    def reply(request: httpx.Request):
        sent.append(request)
        return httpx.Response(200, json={})

    router = R(shipped, env, httpx.MockTransport(reply))
    checked = 0
    async with router._client() as client:
        for op in shipped.operations.values():
            provider = shipped.providers[op.provider]
            hosts = {urlsplit(provider.api).hostname} | {urlsplit(o.api).hostname for o in provider.operations.values() if o.api}
            for route in op.routes:
                given = derive(route.job, {n: SAMPLES[n] for n in route.needs[0] if n in SAMPLES})
                if route.platform:
                    given["platform"] = route.platform
                given["audience"] = route.audience[0] if route.audience[0] != "any" else "professionals"
                assert route.usable(given) is not None, f"{op.id} {route.job} cannot use its own sample"
                sent.clear()
                outcome = await router._attempt(client, op, route, given, 5)
                assert outcome.error != "missing_key", op.id
                assert sent, f"{op.id} {route.job} sent nothing"
                assert {r.url.host for r in sent} <= hosts, op.id
                assert "test-key-123456" not in str(sent[0].url) or provider.key.query or provider.key.body, op.id
                checked += 1
    assert checked >= 100


async def test_audience_keeps_research_sources_out_of_business_searches(tmp_path):
    for name, audience in (("prof", "professionals"), ("lab", "researchers")):
        (tmp_path / f"{name}.yaml").write_text(f"""
id: {name}
title: {name}
docs: https://{name}.example
api: https://api.{name}.example
key: {{}}
operations:
  search:
    request: GET /s
    params: {{q: {{}}}}
    jobs:
      find_people:
        audience: [{audience}]
        needs: [[query]]
        send: {{query: q}}
        result: rows
        fields: {{name: name}}
""")
    hosts = []
    transport = httpx.MockTransport(lambda r: hosts.append(r.url.host) or httpx.Response(200, json={"rows": [{"name": "x"}]}))
    router = Router(Catalog.load(tmp_path), {}, transport)
    await router.run("find_people", {"query": "ml"})
    assert hosts == ["api.prof.example"]
    hosts.clear()
    await router.run("find_people", {"query": "ml", "audience": "researchers"})
    assert hosts == ["api.lab.example"]


async def test_no_match_bodies_are_misses_and_keys_can_travel_in_the_body(tmp_path):
    (tmp_path / "miss.yaml").write_text("""
id: miss
title: Miss
docs: https://miss.example
api: https://api.miss.example
key: {env: MISS_KEY, body: apiKey}
operations:
  enrich:
    request: POST /enrich
    params:
      data: {in: body, type: object}
    no_match: "error_code == 'NO_MATCH'"
    jobs:
      enrich_person:
        needs: [[email]]
        send: {email: data.email}
        result: person
        fields: {name: name}
""")
    bodies = []

    def reply(request: httpx.Request):
        bodies.append(json.loads(request.content))
        return httpx.Response(400, json={"error": True, "error_code": "NO_MATCH"})

    router = Router(Catalog.load(tmp_path), {"MISS_KEY": "body-secret-1"}, httpx.MockTransport(reply))
    result = await router.run("enrich_person", {"email": "ada@acme.com"})
    assert bodies == [{"data": {"email": "ada@acme.com"}, "apiKey": "body-secret-1"}]
    assert result["state"] == "empty" and result["tried"][0]["state"] == "empty"


async def test_templates_build_one_query_from_several_inputs_after_a_fixed_prefix(tmp_path):
    (tmp_path / "web.yaml").write_text("""
id: web
title: Web
docs: https://web.example
api: https://api.web.example
key: {}
operations:
  search:
    request: GET /search
    params:
      q: {}
      filters: {in: query, type: array}
    jobs:
      find_people:
        needs: [[title]]
        send:
          title: {to: q, as: '"$"'}
          location: {to: q, as: "location:$"}
        fixed: {q: "site:linkedin.com/in"}
        result: hits
        fields: {name: name}
""")
    seen = []
    transport = httpx.MockTransport(lambda r: seen.append(r.url.params["q"]) or httpx.Response(200, json={"hits": []}))
    await Router(Catalog.load(tmp_path), {}, transport).run("find_people", {"title": "CTO", "location": "San Francisco"})
    assert seen == ['site:linkedin.com/in "CTO" location:"San Francisco"']


async def test_polling_is_skipped_when_the_first_reply_is_already_final(tmp_path):
    (tmp_path / "quick.yaml").write_text("""
id: quick
title: Quick
docs: https://quick.example
api: https://api.quick.example
key: {}
operations:
  verify:
    request: GET /verify
    params: {email: {required: true}}
    jobs:
      verify_email:
        needs: [[email]]
        send: {email: email}
        poll: {operation: status, send: {id: id}, when: "status != 'success'", until: "status == 'success'", every: 0.01}
        result: '@'
        fields: {status: result}
  status:
    request: GET /status
    params: {id: {required: true}}
""")
    paths = []
    transport = httpx.MockTransport(lambda r: paths.append(r.url.path) or httpx.Response(200, json={"status": "success", "result": "deliverable"}))
    result = await Router(Catalog.load(tmp_path), {}, transport).run("verify_email", {"email": "ada@acme.com"})
    assert paths == ["/verify"]
    assert result["record"]["status"] == "deliverable"


def test_bodies_with_list_indexes_and_whole_bodies(tmp_path):
    from openpeoplerouter.call import build

    (tmp_path / "shape.yaml").write_text("""
id: shape
title: Shape
docs: https://shape.example
api: https://api.shape.example
key: {env: SHAPE_KEY, header: x-key}
operations:
  nested:
    request: POST /n
    params: {contacts: {in: body, type: array}}
  whole:
    request: POST /w
    body: whole
    params: {input: {in: body, type: object}}
""")
    cat = Catalog.load(tmp_path)
    assert cat.problems() == []
    p = cat.providers["shape"]
    req = build(p, p.operations["nested"], {"contacts.0.firstName": "Ada", "contacts.0.lastName": "L"}, {"SHAPE_KEY": "k"})
    assert json.loads(req.content) == {"contacts": [{"firstName": "Ada", "lastName": "L"}]}
    req = build(p, p.operations["whole"], {"input": {"startUrls": ["https://acme.com"]}}, {"SHAPE_KEY": "k"})
    assert json.loads(req.content) == {"startUrls": ["https://acme.com"]}
    assert req.headers["x-key"] == "k"
