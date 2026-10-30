"""Draft a provider file's operations from the provider's published OpenAPI document.

    uv run python scripts/from_openapi.py <spec url or file> [--only /v1/people] [--skip /admin] [--prefix /api]

Prints `operations:` YAML to stdout. Review it, add the header block (id, title, api,
key, docs) and the `jobs:` routes by hand; nothing here guesses how a response maps
onto a job.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx
import yaml

KINDS = {"string", "integer", "number", "boolean", "array", "object"}
SECRET = re.compile(r"^(authorization|token|access_token)$|api[-_]?(key|token)", re.I)  # set by the provider's key block


class _Plain(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _load(source: str) -> dict:
    text = Path(source).read_text() if Path(source).exists() else httpx.get(source, timeout=60, follow_redirects=True).text
    return json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)


def _resolve(spec: dict, node, depth: int = 0):
    while isinstance(node, dict) and "$ref" in node and depth < 20:
        target = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target.get(part.replace("~1", "/").replace("~0", "~"), {})
        node, depth = target, depth + 1
    return node


def _kind(spec: dict, schema) -> str:
    schema = _resolve(spec, schema or {})
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    if not kind:
        for key in ("anyOf", "oneOf", "allOf"):
            for option in schema.get(key) or []:
                found = _kind(spec, option)
                if found != "string":
                    return found
    return kind if kind in KINDS else "string"


CJK = re.compile(r"[\u3400-\u9fff]")
ENGLISH_ONLY = False


def _english(text: str) -> str:
    """'中文说明 / English text' -> 'English text', for bilingual specs."""
    if not ENGLISH_ONLY or not CJK.search(text):
        return text
    parts = [p.strip() for p in re.split(r"\s*/\s*|\n", text) if p.strip() and not CJK.search(p)]
    return " ".join(parts)  # nothing in English: leave it out rather than mix languages


def _about(text: str | None) -> str:
    text = _english(text or "")
    text = re.sub(r"<table.*?</table>", " ", text or "", flags=re.S)
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "|", ">"))]
    text = re.sub(r"<[^>]+>|\*\*|`", "", "\n".join(lines))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200].rsplit(" ", 1)[0] + "…" if len(text) > 200 else text


def _name(op: dict, method: str, path: str, taken: set[str]) -> str:
    base = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", op.get("operationId") or "")
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    base = re.sub(r"-v\d+$", "", base)
    generated = (len(base) > 40 or "endpoint" in base
                 or re.search(r"-(get|post|put|patch|delete|create|list|retrieve|update|destroy)$", base))
    if not base or generated:  # framework-made ids read badly; the path says it better
        parts = [p for p in path.split("/")
                 if p and p != "api" and not p.startswith("{") and not re.fullmatch(r"v\d+(\.\d+)?[a-z]*", p)]
        base = re.sub(r"[^a-z0-9]+", "-", "-".join(parts[-3:]).lower()).strip("-") or "root"
        if base in taken:
            base = f"{method}-{base}"
    base = base[:60]
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    taken.add(name)
    return name


def _param(spec: dict, where: str, schema: dict, required: bool, about: str) -> dict:
    row: dict = {}
    if where != "query":
        row["in"] = where
    kind = _kind(spec, schema)
    if kind != "string":
        row["type"] = kind
    if required:
        row["required"] = True
    resolved = _resolve(spec, schema or {})
    choices = resolved.get("enum")
    if choices and len(choices) <= 12:
        row["choices"] = choices
    if "default" in resolved and resolved["default"] not in (None, "", [], {}) and where in ("header", "path"):
        row["default"] = resolved["default"]
    elif where == "header" and required and len(choices or []) == 1:
        row["default"] = choices[0]
    if about:
        row["about"] = about
    return row


def draft(spec: dict, only: list[str], prefix: str, skip: list[str] = ()) -> dict:
    ops: dict = {}
    taken: set[str] = set()
    for path, item in (spec.get("paths") or {}).items():
        if only and not any(path.startswith(o) for o in only):
            continue
        if any(s in path for s in skip):
            continue
        shared = item.get("parameters") or []
        for method in ("get", "post", "put", "patch", "delete"):
            op = item.get(method)
            if not op or op.get("deprecated"):
                continue
            params: dict = {}
            for p in [*shared, *(op.get("parameters") or [])]:
                p = _resolve(spec, p)
                where = p.get("in")
                if where not in ("query", "path", "header") or SECRET.search(p.get("name", "")):
                    continue
                params[p["name"]] = _param(spec, where, p.get("schema") or {}, bool(p.get("required")), _about(p.get("description")))
            body = _resolve(spec, op.get("requestBody") or {})
            content = body.get("content") or {}
            media = content.get("application/json") or content.get("application/x-www-form-urlencoded")
            form = "application/json" not in content and media is not None
            schema = _resolve(spec, (media or {}).get("schema") or {})
            for key in ("allOf",):
                for part in schema.get(key) or []:
                    part = _resolve(spec, part)
                    schema = {**schema, "properties": {**(schema.get("properties") or {}), **(part.get("properties") or {})},
                              "required": [*(schema.get("required") or []), *(part.get("required") or [])]}
            needed = set(schema.get("required") or [])
            for key in ("oneOf", "anyOf"):  # alternatives: every field, none required
                for part in schema.get(key) or []:
                    part = _resolve(spec, part)
                    schema = {**schema, "properties": {**(part.get("properties") or {}), **(schema.get("properties") or {})}}
            for prop, sub in (schema.get("properties") or {}).items():
                if SECRET.search(prop):
                    continue  # the key is configured on the provider, not passed per call
                sub = _resolve(spec, sub)
                params[prop] = _param(spec, "form" if form else "body", sub, prop in needed, _about(sub.get("description")))
            row = {
                "title": _about(op.get("summary") or op.get("operationId") or "") or f"{method.upper()} {path}",
                "request": f"{method.upper()} {path.removeprefix(prefix) or '/'}",
            }
            about = _about(op.get("description"))
            if about and about != row["title"]:
                row["about"] = about
            if params:
                row["params"] = params
            ops[_name(op, method, path.removeprefix(prefix) or path, taken)] = row
    return ops


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--only", default="", help="comma-separated path prefixes to keep")
    parser.add_argument("--prefix", default="", help="path prefix already in the provider's api URL")
    parser.add_argument("--skip", default="", help="comma-separated path fragments to leave out")
    parser.add_argument("--english", action="store_true", help="keep the English half of bilingual summaries")
    args = parser.parse_args()
    global ENGLISH_ONLY
    ENGLISH_ONLY = args.english
    ops = draft(_load(args.spec), [o for o in args.only.split(",") if o], args.prefix,
                [s for s in args.skip.split(",") if s])
    yaml.dump({"operations": ops}, sys.stdout, Dumper=_Plain, sort_keys=False, allow_unicode=True, width=110)
    print(f"# {len(ops)} operations", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
