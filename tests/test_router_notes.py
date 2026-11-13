"""What a job result tells the caller beyond the rows."""
import httpx

from openpeoplerouter.catalog import Catalog
from openpeoplerouter.router import Router


def _router(handler):
    return Router(Catalog.load(), env={}, transport=httpx.MockTransport(handler))


async def test_github_keywords_are_plain_words_and_only_users():
    seen = {}

    def handler(request):
        seen["q"] = request.url.params["q"]
        return httpx.Response(200, json={"items": [{"login": "a", "html_url": "https://github.com/a"}]})

    out = await _router(handler).run("find_people", {"audience": "developers", "keywords": "rust async"})
    assert seen["q"] == "type:user rust async"
    assert out["state"] == "found" and "ignored" not in out


async def test_inputs_no_tried_provider_received_are_reported():
    def handler(request):
        return httpx.Response(200, json={"results": [{"authorships": [{"author": {"display_name": "A", "id": "x"}}]}]})

    out = await _router(handler).run("find_people", {"audience": "researchers", "keywords": "x", "location": "Germany"}, providers=["openalex"])
    assert out["ignored"] == ["location"]


async def test_unknown_profile_site_is_named_as_such():
    out = await _router(lambda r: httpx.Response(500)).run("read_profile", {"url": "https://example.org/someone"})
    assert out["state"] == "no_provider" and "no provider reads profiles on this site" in out["message"]


async def test_pdl_location_matches_city_region_or_country_and_masked_fields_are_dropped():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"data": [{"full_name": "A B", "job_title": "CTO", "location_name": True, "work_email": False}]})

    router = Router(Catalog.load(), env={"PDL_API_KEY": "k"}, transport=httpx.MockTransport(handler))
    out = await router.run("find_people", {"title": "cto", "location": "London"}, providers=["pdl"])
    assert '"location_locality":"London"' in seen["body"].replace(" ", "") and "location_country" in seen["body"]
    assert out["rows"] == [{"provider": "pdl", "name": "A B", "title": "CTO"}]
