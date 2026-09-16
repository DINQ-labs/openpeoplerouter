"""The tiny expression language the catalog is written in.

Adapters map a vendor's response into a contract with one-line expressions:

    out:
      email: data.email
      confidence: "data.score / 100"
      verified: "data.verification.status == 'valid'"
      name: "join(first_name, last_name)"
    miss: "data.email == null"

Grammar, tried in this order (the first that matches wins):

    comparison   a == b, a != b          right side is a literal or another path
    division     x / 100
    call         name(arg, arg)          from TRANSFORMS; coalesce is special
    literal      null, [], {}, true, false, 'text', "text", 12, 1.5
    path         a.b[0].c, [0].x, .      dotted, with list indexing; "." is the root

Everything is total: a path that does not exist is None rather than an error, so a
vendor that drops a field produces a null in the contract instead of a crash.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

# ---- paths ---------------------------------------------------------------------------------------

_INDEX = re.compile(r"^(?P<name>[^\[\]]*)(?P<idx>(?:\[\d+\])*)$")


def get_path(doc: Any, path: str) -> Any:
    """`a.b[0].c` against nested dicts and lists. Missing anywhere gives None."""
    path = (path or "").strip()
    if not path or path == ".":
        return doc
    cur = doc
    for raw in path.split("."):
        if cur is None:
            return None
        m = _INDEX.match(raw)
        if m is None:
            return None
        name = m.group("name")
        if name:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(name)
        for idx in re.findall(r"\[(\d+)\]", m.group("idx") or ""):
            if not isinstance(cur, list):
                return None
            i = int(idx)
            cur = cur[i] if i < len(cur) else None
    return cur


def set_path(target: dict[str, Any], path: str, value: Any) -> None:
    """`body.a.b = v`, creating the dicts on the way down."""
    parts = [p for p in (path or "").split(".") if p]
    if not parts:
        return
    cur = target
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


# ---- transforms ------------------------------------------------------------------------------------


def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _split_first(value: Any) -> str | None:
    parts = _s(value).split()
    return parts[0] if parts else None


def _split_last(value: Any) -> str | None:
    parts = _s(value).split()
    return parts[-1] if len(parts) > 1 else None


def _join(*values: Any) -> str | None:
    parts = [_s(v).strip() for v in values if _s(v).strip()]
    return " ".join(parts) or None


FREE_MAIL = frozenset(
    {
        "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.jp", "hotmail.com", "outlook.com",
        "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me",
        "qq.com", "163.com", "126.com", "foxmail.com", "sina.com", "gmx.com", "mail.com",
    }
)


def _email_domain(value: Any) -> str | None:
    text = _s(value)
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip().lower()
    return None if not domain or domain in FREE_MAIL else domain


def _host(value: Any) -> str | None:
    text = _s(value).strip()
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    host = (urlparse(text).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


_LINKEDIN_HANDLE = re.compile(r"linkedin\.com/(?:in|pub)/([^/?#]+)", re.IGNORECASE)


def _linkedin_handle(value: Any) -> str | None:
    text = _s(value).strip()
    if not text:
        return None
    m = _LINKEDIN_HANDLE.search(text)
    if m:
        return m.group(1).strip("/").lower()
    return None if "/" in text or "." in text else text.lower()


def _linkedin_url(value: Any) -> str | None:
    text = _s(value).strip()
    if not text:
        return None
    if text.startswith("http"):
        return text
    return f"https://www.linkedin.com/in/{text.strip('/')}"


def _fmt(template: Any, *values: Any) -> str | None:
    if not _s(template):
        return None
    try:
        return _s(template).format(*[_s(v) for v in values])
    except (IndexError, KeyError):
        return None


def _list(value: Any) -> list[Any] | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, list) else [value]


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, dict, str)):
        return len(value)
    return 1


def _at_least(value: Any, minimum: Any) -> Any:
    try:
        return max(float(value), float(minimum))
    except (TypeError, ValueError):
        return value


def _has_type(items: Any, wanted: Any) -> bool:
    if not isinstance(items, list):
        return False
    want = _s(wanted).lower()
    return any(isinstance(i, dict) and _s(i.get("type")).lower() == want for i in items)


def _obj(*pairs: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for i in range(0, len(pairs) - 1, 2):
        out[_s(pairs[i])] = pairs[i + 1]
    return out


def _csv(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ",".join(_s(v) for v in value if _s(v)) or None
    return _s(value) or None


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


_COUNTRIES: dict[str, str] | None = None


def _country_name(value: Any) -> str | None:
    """`country_name('fr')` -> 'France'.

    Some vendors filter on a country code and some on the written name. The catalog
    says which by wrapping the field in this; a name passed in comes back unchanged."""
    global _COUNTRIES
    text = _s(value).strip()
    if not text:
        return None
    if _COUNTRIES is None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[3] / "catalog" / "countries.json"
        try:
            _COUNTRIES = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _COUNTRIES = {}
    return _COUNTRIES.get(text.lower(), text)


def _tca_filter(attribute: Any, value: Any) -> str | None:
    """The Companies API takes its filters as a JSON string in one query parameter."""
    if value in (None, "", [], {}):
        return None
    import json

    return json.dumps([{"attribute": _s(attribute), "operator": "or", "sign": "equals", "values": [value]}])


def _first_value(rows: Any) -> str | None:
    """The first `value` out of a `contacts(...)` list — for contracts that want one
    email rather than all of them."""
    if isinstance(rows, list) and rows:
        head = rows[0]
        if isinstance(head, dict):
            return head.get("value")
        return _s(head) or None
    return None


PLATFORMS: tuple[tuple[str, str], ...] = (
    ("linkedin.com", "linkedin"),
    ("github.com", "github"),
    ("huggingface.co", "huggingface"),
    ("scholar.google.com", "scholar"),
    ("openreview.net", "openreview"),
    ("twitter.com", "x"),
    ("x.com", "x"),
    ("medium.com", "medium"),
    ("stackoverflow.com", "stackoverflow"),
    ("kaggle.com", "kaggle"),
    ("orcid.org", "orcid"),
    ("gitlab.com", "gitlab"),
    ("dribbble.com", "dribbble"),
    ("behance.net", "behance"),
    ("instagram.com", "instagram"),
    ("facebook.com", "facebook"),
    ("youtube.com", "youtube"),
    ("tiktok.com", "tiktok"),
    ("reddit.com", "reddit"),
    ("crunchbase.com", "crunchbase"),
)


def _platform_from_host(url: str) -> str:
    host = _host(url) or ""
    for suffix, name in PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return name
    return "web"


def _handle_of(url: str) -> str | None:
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    # Some platforms put the identity in the query string rather than the path.
    for key in ("user", "id", "profileId"):
        found = parse_qs(parsed.query or "").get(key)
        if found and found[0]:
            return found[0]
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        return None
    skip = {"in", "pub", "citations", "papers", "user", "users", "profile", "u", "c", "@"}
    for part in parts:
        if part.lower() not in skip and not part.lower().startswith("@"):
            return part
    return parts[-1].lstrip("@") or None


def _canonical_url(url: str) -> str:
    """One spelling per profile.

    Two vendors naming the same LinkedIn as `http://www.linkedin.com/in/ada` and
    `https://www.linkedin.com/in/ada/` are naming one profile, and identity resolution
    is exactly the place where that has to count once."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    host = host.removeprefix("www.")
    path = (parsed.path or "").rstrip("/")
    return urlunparse(("https", host, path, "", parsed.query, ""))


def _platform_of(url_or_name: Any) -> str | None:
    """Which platform a profile URL belongs to. A bare platform name passes through."""
    text = _s(url_or_name).strip().lower()
    if not text:
        return None
    if "/" not in text and "." not in text:
        return text
    found = _platform_from_host(text)
    return found if found != "web" else None


def _handle_of_url(url: Any) -> str | None:
    text = _s(url).strip()
    return _handle_of(text) if text else None


_PROFILE_ROOT = {
    "x": "https://x.com/{handle}",
    "instagram": "https://www.instagram.com/{handle}",
    "tiktok": "https://www.tiktok.com/@{handle}",
    "github": "https://github.com/{handle}",
    "threads": "https://www.threads.net/@{handle}",
    "bluesky": "https://bsky.app/profile/{handle}",
    "reddit": "https://www.reddit.com/user/{handle}",
    "linkedin": "https://www.linkedin.com/in/{handle}",
}


def _profiles(*urls: Any) -> list[dict[str, Any]]:
    """Turn whatever URLs a vendor returned into one row per platform.

    The point of identity resolution is a person's whole surface, so this accepts
    single URLs, lists of them, and already-made rows, and quietly drops repeats."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                add(item)
            return
        if isinstance(value, dict):
            value = value.get("url") or value.get("value") or value.get("link")
        text = _s(value).strip()
        if not text or "." not in text:
            return
        if not text.startswith("http"):
            text = "https://" + text.lstrip("/")
        text = _canonical_url(text)
        platform = _platform_from_host(text)
        handle = _handle_of(text)
        # A post is not a profile. On platforms whose profile URL is host/handle, a link to
        # a status or a post collapses to the account it belongs to, and counts once.
        root = _PROFILE_ROOT.get(platform)
        if root and handle:
            text = root.format(handle=handle)
        key = f"{platform}:{handle}".lower() if platform != "web" and handle else text.lower()
        if key in seen:
            return
        seen.add(key)
        row: dict[str, Any] = {"platform": platform, "url": text}
        if handle:
            row["handle"] = handle
        out.append(row)

    for url in urls:
        add(url)
    return out


def _where(items: Any, key: Any, *values: Any) -> list[Any]:
    """Keep the rows of a list whose `key` is one of `values`."""
    if not isinstance(items, list):
        return []
    wanted = {_s(v).lower() for v in values}
    return [i for i in items if isinstance(i, dict) and _s(i.get(_s(key))).lower() in wanted]


def _contacts(items: Any, value_key: Any = "value", type_key: Any = None, confidence_key: Any = None) -> list[dict[str, Any]]:
    """Normalise a vendor's emails or phones into `{value, type, confidence}` rows.

    Accepts a list of strings or of dicts, and a bare string, because vendors do all
    three for the same field."""
    if items is None:
        return []
    rows = items if isinstance(items, list) else [items]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if isinstance(item, str):
            value: Any = item
            extra: dict[str, Any] = {}
        elif isinstance(item, dict):
            value = item.get(_s(value_key)) or item.get("value") or item.get("email") or item.get("number")
            extra = {}
            if type_key and item.get(_s(type_key)):
                extra["type"] = item[_s(type_key)]
            if confidence_key and item.get(_s(confidence_key)) is not None:
                extra["confidence"] = item[_s(confidence_key)]
        else:
            continue
        text = _s(value).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append({"value": text, **extra})
    return out



def _spec_value(item: Any, spec: str) -> Any:
    """A tiny field spec for one vendor's row: `a.b` is a path, `a|b` is a fallback,
    `a+b` joins with a space. Enough to name a person or a company in any vendor's shape."""
    for alternative in (spec or "").split("|"):
        alternative = alternative.strip()
        if not alternative:
            continue
        if "+" in alternative:
            parts = [get_path(item, p.strip()) for p in alternative.split("+")]
            joined = " ".join(str(v).strip() for v in parts if v not in (None, ""))
            if joined:
                return joined
            continue
        value = get_path(item, alternative)
        if value not in (None, "", [], {}):
            return value
    return None


def _as_url(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


def _as_domain(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    host = _host(value) if "/" in value or "://" in value else value.strip().lower()
    return host.removeprefix("www.") or None


def _pluck(items: Any, key: str) -> list[Any]:
    """One key's values out of a list of rows, for feeding a list into another transform."""
    if not isinstance(items, list):
        return []
    return [get_path(item, key) for item in items if isinstance(item, dict) and get_path(item, key) not in (None, "")]


def _join_url(prefix: Any, value: Any) -> str | None:
    """A URL from an id, or nothing: unlike fmt(), an empty id yields no URL at all,
    which is what a profile list needs."""
    if value in (None, "", [], {}):
        return None
    return f"{_s(prefix)}{_s(value).strip().lstrip('@')}"


def _doi_of(value: Any) -> str | None:
    """ from a DOI URL or a bare DOI."""
    text = _s(value).strip()
    if not text:
        return None
    m = re.search(r"(10\.\d{4,9}/\S+)", text)
    return m.group(1).rstrip("/") if m else None


def _rows(items: Any, name: str, url: str = "", domain: str = "", url_prefix: str = "") -> list[dict[str, Any]]:
    """The thin row every list capability answers with, whoever served it.

    Vendors disagree about everything but the two things an agent needs to carry a row
    into the next job: a name, and a handle — a profile URL or a domain. Those are
    lifted to the top of the row; the vendor's own row rides along under `data`, whole,
    because the agent can read it and we should not pretend to know it better."""
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {"name": _spec_value(item, name)}
        raw_link = _spec_value(item, url) if url else None
        link = _join_url(url_prefix, raw_link) if url_prefix else _as_url(raw_link)
        site = _as_domain(_spec_value(item, domain)) if domain else None
        if link:
            row["url"] = link
        if site:
            row["domain"] = site
        row["data"] = item
        out.append(row)
    return out


TRANSFORMS: dict[str, Callable[..., Any]] = {
    "split_first": _split_first,
    "split_last": _split_last,
    "join": _join,
    "lower": lambda v: _s(v).lower() or None,
    "upper": lambda v: _s(v).upper() or None,
    "strip": lambda v: _s(v).strip() or None,
    "len": _len,
    "list": _list,
    "first": _first,
    "at_least": _at_least,
    "has_type": _has_type,
    "linkedin_handle": _linkedin_handle,
    "linkedin_url": _linkedin_url,
    "email_domain": _email_domain,
    "host": _host,
    "fmt": _fmt,
    "obj": _obj,
    "csv": _csv,
    "nonempty": _nonempty,
    "where": _where,
    "profiles": _profiles,
    "platform_of": _platform_of,
    "handle_of": _handle_of_url,
    "first_value": _first_value,
    "country_name": _country_name,
    "tca_filter": _tca_filter,
    "contacts": _contacts,
    "rows": _rows,
    "join_url": _join_url,
    "pluck": _pluck,
    "doi_of": _doi_of,
    "bool": lambda v: bool(v),
    "int": lambda v: int(v) if isinstance(v, (int, float)) or _s(v).lstrip("-").isdigit() else None,
}

# ---- evaluate ----------------------------------------------------------------------------------------

_COMPARE = re.compile(r"^(?P<left>.+?)\s*(?P<op>==|!=)\s*(?P<right>.+)$")
_DIVIDE = re.compile(r"^(?P<left>[^/]+?)\s*/\s*(?P<right>[0-9.]+)$")
_CALL = re.compile(r"^(?P<name>[a-z_][a-z0-9_]*)\((?P<args>.*)\)$", re.IGNORECASE | re.DOTALL)
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _split_args(raw: str) -> list[str]:
    """Top-level comma split that respects nesting and quotes."""
    args, depth, quote, buf = [], 0, "", []
    for ch in raw:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in "([":
            depth += 1
            buf.append(ch)
        elif ch in ")]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def _literal(expr: str) -> tuple[bool, Any]:
    text = expr.strip()
    if text == "null" or text == "None":
        return True, None
    if text == "[]":
        return True, []
    if text == "{}":
        return True, {}
    if text in ("true", "True"):
        return True, True
    if text in ("false", "False"):
        return True, False
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return True, text[1:-1]
    if _NUMBER.match(text):
        return True, float(text) if "." in text else int(text)
    return False, None


def evaluate(expr: str, doc: Any) -> Any:
    """Run one adapter expression against a document."""
    if expr is None:
        return None
    text = str(expr).strip()
    if not text:
        return None

    m = _COMPARE.match(text)
    if m:
        left = evaluate(m.group("left"), doc)
        right_expr = m.group("right").strip()
        is_lit, lit = _literal(right_expr)
        right = lit if is_lit else evaluate(right_expr, doc)
        return left == right if m.group("op") == "==" else left != right

    m = _CALL.match(text)
    if m:
        name = m.group("name")
        args_raw = _split_args(m.group("args"))
        if name == "coalesce":
            for arg in args_raw:
                value = evaluate(arg, doc)
                if value not in (None, "", [], {}):
                    return value
            return None
        fn = TRANSFORMS.get(name)
        if fn is None:
            return None
        args = [evaluate(a, doc) for a in args_raw]
        try:
            return fn(*args)
        except (TypeError, ValueError):
            return None

    m = _DIVIDE.match(text)
    if m:
        left = evaluate(m.group("left"), doc)
        try:
            return float(left) / float(m.group("right"))
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    is_lit, lit = _literal(text)
    if is_lit:
        return lit

    return get_path(doc, text)
