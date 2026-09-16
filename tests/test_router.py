import httpx
import pytest
from fastmcp import Client
from openpeoplerouter.catalog.store import load_catalog
from openpeoplerouter.router import Router
from openpeoplerouter.server import create_server


def test_catalog_standalone():
    cat = load_catalog()
    assert not cat.problems
    assert len(cat.contracts) == 8
    assert len(cat.endpoints) > 1500
    assert all(v.base_url.startswith('https://') for v in cat.vendors.values())
    assert all(v.auth.credential != 'DINQ_MCP_API_KEY' for v in cat.vendors.values())


@pytest.mark.asyncio
async def test_real_mcp_protocol_schemas_and_routing():
    seen = []
    def reply(req):
        seen.append(req)
        assert req.url.host == 'api.openalex.org'
        assert 'secret' not in str(req.url)
        return httpx.Response(200, json={'results':[{'display_name':'Example Researcher','orcid':'https://orcid.org/example'}], 'meta':{'count':1}})
    router = Router(load_catalog(), {'OPENPEOPLEROUTER_PROVIDERS':'openalex'}, httpx.MockTransport(reply))
    async with Client(create_server(router)) as client:
        tools = await client.list_tools()
        assert len(tools) == 12
        assert {'people_search','find_tool','endpoint','call_tool'} <= {t.name for t in tools}
        assert all('max_credits' not in t.inputSchema.get('properties',{}) for t in tools)
        result = await client.call_tool('people_search', {'q':'Example','vendor':'openalex'})
        assert result.data['outcome'] == 'hit'
        assert result.data['output']['people'][0]['name'] == 'Example Researcher'
        assert len(seen) == 1
        caps = (await client.call_tool('capabilities')).data
        assert len(caps['capabilities']) == 8
        found = (await client.call_tool('find_tool', {'query':'instagram','limit':3})).data
        assert found['tools']
        assert all(not r['configured'] for r in found['tools'])


@pytest.mark.asyncio
async def test_own_key_only_to_selected_provider():
    seen=[]
    def reply(req):
        seen.append(req)
        assert req.url.host == 'api.hunter.io'
        assert req.headers['X-API-KEY'] == 'user-owned-example'
        return httpx.Response(200,json={'data':{'email':'person@example.org'}})
    router=Router(load_catalog(),{'HUNTER_API_KEY':'user-owned-example'},httpx.MockTransport(reply))
    result=await router.call('hunter.people.email.find',{'first_name':'Example','last_name':'Person','domain':'example.org'})
    assert result['outcome']=='hit'
    assert len(seen)==1
    assert 'user-owned-example' not in str(result)
    no_key=Router(load_catalog(),{},httpx.MockTransport(reply))
    assert (await no_key.call('hunter.people.email.find',{}))['error']['code']=='missing_credential'
    assert len(seen)==1


@pytest.mark.asyncio
async def test_dinq_optional_and_only_explicit():
    router=Router(load_catalog(),{'DINQ_API_KEY':'example','OPENPEOPLEROUTER_PROVIDERS':'dinq'})
    calls=[]
    async def fake(cap,args):
        calls.append(cap)
        return {'outcome':'hit','output':{'people':[]}}
    router.dinq=fake
    assert (await router.run('people.search',{'q':'example'}))['outcome']=='error'
    assert calls==[]
    assert (await router.run('people.search',{'q':'example'},{'vendor':'dinq'}))['outcome']=='hit'
    assert calls==['people.search']


@pytest.mark.asyncio
async def test_disabled_provider_never_called_and_errors_are_structured():
    def fail(req):
        raise httpx.ReadTimeout('timed out')
    router=Router(load_catalog(),{'OPENPEOPLEROUTER_PROVIDERS':'openalex'},httpx.MockTransport(fail))
    response=await router.run('people.search',{'q':'example'})
    assert response['outcome']=='error'
    assert response['_meta']['tried'][0]['error']['code']=='timeout'
    assert (await router.call('orcid.people.search',{}))['error']['code']=='missing_credential'


@pytest.mark.asyncio
async def test_credentials_redacted_from_provider_error_or_echo():
    key='private-test-key-123'
    router=Router(load_catalog(),{'HUNTER_API_KEY':key},httpx.MockTransport(lambda req: httpx.Response(200,json={'echo':key})))
    result=await router.call('hunter.people.email.find',{'domain':'example.org'})
    assert key not in str(result)
    assert result['raw']['echo']=='[redacted]'


@pytest.mark.asyncio
async def test_dinq_bridge_protocol_with_synthetic_provider(monkeypatch):
    from fastmcp import FastMCP
    import openpeoplerouter.router as module
    provider=FastMCP('Synthetic DINQ')
    @provider.tool
    async def people_search(q: str):
        return {'outcome':'hit','output':{'people':[{'name':q}]}}
    def factory(url,auth,timeout):
        assert url=='https://router.dinq.me/test'
        assert auth=='example-key'
        return Client(provider)
    monkeypatch.setattr(module,'Client',factory)
    router=Router(load_catalog(),{'DINQ_API_KEY':'example-key'})
    result=await router.run('people.search',{'q':'Example'},{'vendor':'dinq'})
    assert result['output']['people'][0]['name']=='Example'
    assert result['_meta']['provider']=='dinq'
