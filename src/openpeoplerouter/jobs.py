"""The jobs an agent asks for, independent of who answers them.

A job names its inputs and the fields it returns. Providers opt in per operation
with a `jobs:` block (see docs/provider-format.md); the router picks among them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


AUDIENCES = ("professionals", "researchers", "developers", "creators")


@dataclass(frozen=True)
class Job:
    name: str
    description: str
    inputs: dict[str, str]  # name -> what it is
    fields: tuple[str, ...]  # what each answer carries
    many: bool = False  # a list of rows, merged across providers, or one record
    defaults: dict[str, Any] = field(default_factory=dict)


PERSON_FIELDS = (
    "name", "first_name", "last_name", "title", "company", "company_domain", "location",
    "country", "headline", "linkedin_url", "url", "email", "phone", "image",
)
COMPANY_FIELDS = (
    "name", "domain", "website", "description", "industry", "employees", "founded",
    "location", "country", "linkedin_url", "url", "logo",
)

JOBS: dict[str, Job] = {
    job.name: job
    for job in (
        Job(
            "find_people",
            "Find people you do not have yet: by role, employer, place, skills or a free-text "
            "description. Returns a merged list from the providers you have configured.",
            {
                "query": "free-text description of who you are looking for",
                "title": "job title or role",
                "company": "employer name",
                "company_domain": "employer domain, e.g. stripe.com",
                "location": "city, region or country, as free text",
                "country": "ISO 3166 alpha-2 country code",
                "seniority": "entry | senior | manager | director | vp | c_suite",
                "keywords": "skills or topics, comma separated",
                "audience": "professionals (default) | researchers | developers | creators: which kind of "
                            "source to search",
                "limit": "how many people to return",
            },
            PERSON_FIELDS,
            many=True,
            defaults={"limit": 25, "audience": "professionals"},
        ),
        Job(
            "enrich_person",
            "Complete one person you can already identify: current role, employer, location "
            "and profiles, from an email, a LinkedIn URL, or a name with an employer.",
            {
                "email": "an email address of the person",
                "linkedin_url": "their LinkedIn profile URL",
                "full_name": "full name",
                "company": "employer name, used with the name",
                "company_domain": "employer domain, used with the name",
                "phone": "a phone number of the person",
            },
            PERSON_FIELDS + ("skills", "experience", "education"),
        ),
        Job(
            "find_contact",
            "Work email (and phone where the provider sells it) for one person, from a name "
            "and company domain or a LinkedIn URL.",
            {
                "full_name": "full name",
                "first_name": "first name",
                "last_name": "last name",
                "company_domain": "employer domain",
                "company": "employer name, when the domain is unknown",
                "linkedin_url": "their LinkedIn profile URL",
            },
            ("email", "email_status", "phone", "confidence", "name", "title", "company_domain"),
        ),
        Job(
            "verify_email",
            "Check whether an email address can receive mail before you send to it.",
            {"email": "the address to check"},
            ("email", "status", "deliverable", "score", "catch_all", "disposable"),
        ),
        Job(
            "find_companies",
            "Find companies by industry, size, place, technology or a free-text description.",
            {
                "query": "free-text description of the companies",
                "industry": "industry or sector",
                "location": "city, region or country, as free text",
                "country": "ISO 3166 alpha-2 country code",
                "employees": "headcount range, e.g. 51-200",
                "technology": "a technology the company uses",
                "limit": "how many companies to return",
            },
            COMPANY_FIELDS,
            many=True,
            defaults={"limit": 25},
        ),
        Job(
            "enrich_company",
            "Facts about one company from its domain, name or LinkedIn page: size, industry, "
            "location, links.",
            {
                "domain": "company domain, e.g. stripe.com",
                "name": "company name",
                "linkedin_url": "the company's LinkedIn page",
            },
            COMPANY_FIELDS + ("funding", "revenue", "technologies"),
        ),
        Job(
            "read_profile",
            "One public social or developer profile: bio, follower counts, links. Give a "
            "profile URL, or a platform and handle.",
            {
                "url": "profile URL",
                "platform": "linkedin | x | instagram | tiktok | youtube | github | huggingface | "
                            "threads | bluesky | reddit | facebook | twitch | pinterest | snapchat",
                "handle": "username on that platform",
            },
            ("name", "handle", "platform", "bio", "followers", "following", "posts", "verified",
             "location", "website", "url", "image"),
        ),
    )
}

PLATFORM_HOSTS = {
    "linkedin.com": "linkedin", "x.com": "x", "twitter.com": "x", "instagram.com": "instagram",
    "tiktok.com": "tiktok", "youtube.com": "youtube", "github.com": "github",
    "threads.net": "threads", "threads.com": "threads", "bsky.app": "bluesky",
    "reddit.com": "reddit", "facebook.com": "facebook", "twitch.tv": "twitch",
    "pinterest.com": "pinterest", "snapchat.com": "snapchat", "huggingface.co": "huggingface",
}


def _host(value: str) -> str:
    text = value.strip()
    host = urlsplit(text if "//" in text else "//" + text).hostname or ""
    return host.lower().removeprefix("www.")


def derive(job: str, given: dict[str, Any]) -> dict[str, Any]:
    """Fill the inputs that follow from the ones supplied, so a provider that wants
    first and last name can serve a caller who gave a full name."""
    out = {k: v for k, v in given.items() if v not in (None, "", [])}
    if out.get("full_name") and not (out.get("first_name") and out.get("last_name")):
        parts = str(out["full_name"]).split()
        if len(parts) > 1:
            out.setdefault("first_name", parts[0])
            out.setdefault("last_name", " ".join(parts[1:]))
    if out.get("first_name") and out.get("last_name") and not out.get("full_name"):
        out["full_name"] = f"{out['first_name']} {out['last_name']}"
    for key in ("company_domain", "domain"):
        if out.get(key):
            out[key] = _host(str(out[key])) or out[key]
    if job == "read_profile" and out.get("url") and not out.get("platform"):
        host = _host(str(out["url"]))
        platform = next((p for h, p in PLATFORM_HOSTS.items() if host == h or host.endswith("." + h)), None)
        if platform:
            out["platform"] = platform
            path = [p for p in urlsplit(str(out["url"])).path.split("/") if p]
            if path and not out.get("handle"):
                skip = {"in", "company", "user", "c", "channel", "u", "r", "profile", "profile.php"}
                handle = next((p for p in path if p not in skip), "")
                out["handle"] = handle.lstrip("@")
    if out.get("handle"):
        out["handle"] = str(out["handle"]).lstrip("@")
    if out.get("linkedin_url"):
        match = re.search(r"linkedin\.com/(?:in|company|school)/([^/?#]+)", str(out["linkedin_url"]))
        if match:
            out.setdefault("linkedin_handle", match.group(1))
    return out
