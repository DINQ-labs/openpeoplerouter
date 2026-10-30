# Providers

Every provider in the catalog, the variable its key is read from, and the jobs it serves. Operations without a job are reachable through `search_operations` and `call_operation`.

Regenerate with `openpeoplerouter providers --markdown`.

| Provider | Key variable | Jobs | Operations | Docs |
| --- | --- | --- | --- | --- |
| [Akta](https://akta.pro) | `AKTA_API_KEY` | find_companies | 14 | [docs](https://docs.akta.pro) |
| [Anymailfinder](https://anymailfinder.com) | `ANYMAILFINDER_API_KEY` | find_contact, verify_email | 11 | [docs](https://anymailfinder.com/email-finder-api/docs) |
| [Apify](https://apify.com) | `APIFY_TOKEN` | — | 7 | [docs](https://docs.apify.com/api/v2) |
| [Apollo](https://www.apollo.io) | `APOLLO_API_KEY` | enrich_company, enrich_person, find_companies, find_contact, find_people | 11 | [docs](https://docs.apollo.io/reference/apollo-api) |
| [BlitzAPI](https://blitz-api.ai) | `BLITZAPI_API_KEY` | — | 19 | [docs](https://docs.blitz-api.ai) |
| [Bluesky](https://bsky.app) | none | find_people, read_profile | 4 | [docs](https://docs.bsky.app/docs/category/http-reference) |
| [BounceBan](https://bounceban.com) | `BOUNCEBAN_API_KEY` | verify_email | 4 | [docs](https://bounceban.com/public/doc/api.html) |
| [Bouncer](https://www.usebouncer.com) | `BOUNCER_API_KEY` | verify_email | 11 | [docs](https://docs.usebouncer.com) |
| [Brave Search](https://brave.com/search/api/) | `BRAVE_SEARCH_API_KEY` | find_people | 2 | [docs](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started) |
| [Clearout](https://clearout.io) | `CLEAROUT_API_TOKEN` | find_contact, verify_email | 31 | [docs](https://docs.clearout.io/developers/api/overview) |
| [CompanyEnrich](https://companyenrich.com) | `COMPANYENRICH_API_KEY` | enrich_company, enrich_person, find_companies, find_people | 43 | [docs](https://docs.companyenrich.com) |
| [ContactOut](https://contactout.com) | `CONTACTOUT_API_TOKEN` | enrich_company, enrich_person, find_companies, find_contact, find_people | 11 | [docs](https://api.contactout.com/) |
| [Context.dev](https://www.context.dev) | `CONTEXTDEV_API_KEY` | enrich_company, enrich_person, find_companies, find_people | 15 | [docs](https://docs.context.dev) |
| [Coresignal](https://coresignal.com) | `CORESIGNAL_API_KEY` | enrich_company, enrich_person | 44 | [docs](https://docs.coresignal.com) |
| [Crossref](https://www.crossref.org) | `CROSSREF_MAILTO` | — | 2 | [docs](https://api.crossref.org/swagger-ui/index.html) |
| [Crunchbase](https://www.crunchbase.com) | `CRUNCHBASE_API_KEY` | — | 5 | [docs](https://data.crunchbase.com/docs/api-essentials) |
| [Crustdata](https://crustdata.com) | `CRUSTDATA_API_KEY` | enrich_company, enrich_person, find_companies, find_contact, find_people | 16 | [docs](https://docs.crustdata.com) |
| [Diffbot Knowledge Graph](https://www.diffbot.com) | `DIFFBOT_TOKEN` | enrich_company, enrich_person, find_people | 6 | [docs](https://docs.diffbot.com/kgapi) |
| [Dropcontact](https://www.dropcontact.com) | `DROPCONTACT_API_KEY` | find_contact | 2 | [docs](https://developer.dropcontact.com/) |
| [Emailable](https://emailable.com) | `EMAILABLE_API_KEY` | verify_email | 4 | [docs](https://emailable.com/docs/api/) |
| [Enrich Layer](https://enrichlayer.com) | `ENRICHLAYER_API_KEY` | enrich_company, enrich_person, find_people | 24 | [docs](https://enrichlayer.com/docs/api/v2) |
| [Enrow](https://enrow.io) | `ENROW_API_KEY` | find_contact, verify_email | 9 | [docs](https://docs.enrow.io) |
| [Exa](https://exa.ai) | `EXA_API_KEY` | find_companies, find_people | 7 | [docs](https://docs.exa.ai) |
| [Fiber AI](https://fiber.ai) | `FIBER_API_KEY` | enrich_person, find_contact, find_people, verify_email | 50 | [docs](https://docs.fiber.ai) |
| [Findymail](https://www.findymail.com) | `FINDYMAIL_API_KEY` | enrich_company, find_contact, find_people, verify_email | 10 | [docs](https://app.findymail.com/docs/) |
| [Firecrawl](https://www.firecrawl.dev) | `FIRECRAWL_API_KEY` | — | 31 | [docs](https://docs.firecrawl.dev) |
| [FullEnrich](https://fullenrich.com) | `FULLENRICH_API_KEY` | enrich_company, enrich_person, find_companies, find_contact, find_people | 10 | [docs](https://docs.fullenrich.com/api/v2/general/introduction) |
| [GitHub](https://github.com) | `GITHUB_TOKEN` | find_people, read_profile | 8 | [docs](https://docs.github.com/en/rest) |
| [HarvestAPI](https://harvest-api.com) | `HARVESTAPI_API_KEY` | enrich_company, enrich_person, find_people, read_profile | 26 | [docs](https://docs.harvest-api.com) |
| [Hugging Face](https://huggingface.co) | `HF_TOKEN` | read_profile | 7 | [docs](https://huggingface.co/docs/hub/api) |
| [Hunter](https://hunter.io) | `HUNTER_API_KEY` | enrich_company, enrich_person, find_companies, find_contact, find_people, verify_email | 9 | [docs](https://hunter.io/api-documentation/v2) |
| [Influencers.club](https://influencers.club) | `INFLUENCERSCLUB_API_KEY` | enrich_person, find_people, read_profile | 29 | [docs](https://docs.influencers.club) |
| [Jina AI](https://jina.ai) | `JINA_API_KEY` | — | 2 | [docs](https://jina.ai/reader/) |
| [Just One API](https://justoneapi.com) | `JUSTONEAPI_TOKEN` | — | 216 | [docs](https://docs.justoneapi.com) |
| [Kickbox](https://kickbox.com) | `KICKBOX_API_KEY` | verify_email | 2 | [docs](https://docs.kickbox.com/docs/single-verification-api) |
| [LeadMagic](https://leadmagic.io) | `LEADMAGIC_API_KEY` | enrich_company, enrich_person, find_contact, find_people, verify_email | 37 | [docs](https://docs.leadmagic.io) |
| [Linkup](https://www.linkup.so) | `LINKUP_API_KEY` | — | 9 | [docs](https://docs.linkup.so) |
| [Lusha](https://www.lusha.com) | `LUSHA_API_KEY` | enrich_company, enrich_person, find_companies, find_contact, find_people | 33 | [docs](https://docs.lusha.com) |
| [MillionVerifier](https://www.millionverifier.com) | `MILLIONVERIFIER_API_KEY` | verify_email | 2 | [docs](https://developer.millionverifier.com/) |
| [NeverBounce](https://neverbounce.com) | `NEVERBOUNCE_API_KEY` | verify_email | 2 | [docs](https://developers.neverbounce.com/reference/single-check) |
| [Ocean.io](https://www.ocean.io) | `OCEANIO_API_TOKEN` | enrich_company, enrich_person | 24 | [docs](https://docs.ocean.io) |
| [OpenAlex](https://openalex.org) | `OPENALEX_API_KEY` | find_people | 4 | [docs](https://help.openalex.org) |
| [ORCID](https://orcid.org) | `ORCID_ACCESS_TOKEN` | find_people | 4 | [docs](https://info.orcid.org/documentation/api-tutorials/api-tutorial-searching-the-orcid-registry/) |
| [Parallel](https://parallel.ai) | `PARALLEL_API_KEY` | find_companies, find_people | 15 | [docs](https://docs.parallel.ai) |
| [People Data Labs](https://www.peopledatalabs.com) | `PDL_API_KEY` | enrich_company, enrich_person, find_companies, find_contact, find_people | 11 | [docs](https://docs.peopledatalabs.com) |
| [Perplexity](https://www.perplexity.ai) | `PERPLEXITY_API_KEY` | — | 5 | [docs](https://docs.perplexity.ai) |
| [Prospeo](https://prospeo.io) | `PROSPEO_API_KEY` | enrich_company, enrich_person, find_contact, find_people | 7 | [docs](https://prospeo.io/api-docs) |
| [RocketReach](https://rocketreach.co) | `ROCKETREACH_API_KEY` | enrich_company, enrich_person, find_companies, find_contact, find_people | 6 | [docs](https://docs.rocketreach.co/reference/rocketreach-api) |
| [ScrapeCreators](https://scrapecreators.com) | `SCRAPECREATORS_API_KEY` | enrich_person, find_people, read_profile | 168 | [docs](https://docs.scrapecreators.com) |
| [Semantic Scholar](https://www.semanticscholar.org) | `SEMANTIC_SCHOLAR_API_KEY` | find_people | 5 | [docs](https://api.semanticscholar.org/api-docs/graph) |
| [SerpApi](https://serpapi.com) | `SERPAPI_API_KEY` | find_people | 4 | [docs](https://serpapi.com/search-api) |
| [Serper](https://serper.dev) | `SERPER_API_KEY` | find_people | 6 | [docs](https://serper.dev/playground) |
| [Sixtyfour](https://www.sixtyfour.ai) | `SIXTYFOUR_API_KEY` | find_contact, verify_email | 28 | [docs](https://docs.sixtyfour.ai) |
| [Stack Exchange](https://stackexchange.com) | `STACKEXCHANGE_KEY` | find_people | 4 | [docs](https://api.stackexchange.com/docs) |
| [Sumble](https://sumble.com) | `SUMBLE_API_KEY` | enrich_company, enrich_person | 14 | [docs](https://docs.sumble.com) |
| [Tavily](https://tavily.com) | `TAVILY_API_KEY` | — | 7 | [docs](https://docs.tavily.com) |
| [The Companies API](https://www.thecompaniesapi.com) | `THECOMPANIESAPI_API_KEY` | enrich_company, find_companies | 25 | [docs](https://www.thecompaniesapi.com/api) |
| [TheirStack](https://theirstack.com) | `THEIRSTACK_API_KEY` | find_companies | 14 | [docs](https://theirstack.com/en/docs/api-reference) |
| [TikHub](https://tikhub.io) | `TIKHUB_API_KEY` | — | 1039 | [docs](https://api.tikhub.io/docs) |
| [TinyFish](https://www.tinyfish.ai) | `TINYFISH_API_KEY` | — | 5 | [docs](https://docs.tinyfish.ai) |
| [Tomba](https://tomba.io) | `TOMBA_API_KEY`, `TOMBA_SECRET` | enrich_company, enrich_person, find_companies, find_contact, find_people, verify_email | 20 | [docs](https://docs.tomba.io) |
| [Trestle](https://trestleiq.com) | `TRESTLE_API_KEY` | enrich_person | 5 | [docs](https://docs.trestleiq.com) |
| [Valyu](https://www.valyu.ai) | `VALYU_API_KEY` | — | 14 | [docs](https://docs.valyu.ai) |
| [Wikidata](https://www.wikidata.org) | none | — | 2 | [docs](https://www.wikidata.org/wiki/Wikidata:Data_access) |
| [Wiza](https://wiza.co) | `WIZA_API_KEY` | enrich_person, find_contact, find_people | 8 | [docs](https://docs.wiza.co) |
| [X API](https://developer.x.com) | `X_BEARER_TOKEN` | find_people, read_profile | 10 | [docs](https://docs.x.com/x-api/introduction) |
| [YouTube Data API](https://developers.google.com/youtube/v3) | `YOUTUBE_API_KEY` | find_people, read_profile | 5 | [docs](https://developers.google.com/youtube/v3/docs) |
| [ZeroBounce](https://www.zerobounce.net) | `ZEROBOUNCE_API_KEY` | find_contact, verify_email | 4 | [docs](https://www.zerobounce.net/docs/) |

