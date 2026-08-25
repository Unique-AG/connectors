#!/usr/bin/env python3
"""Read Backstop's Elevio help center. Not part of the shipped MCP server.

Elevio is a different host and a different credential from the REST API. The service
API token cannot read it. This script SSOs through help-prod with a web username and
password (POST j_security_check there only — never against BACKSTOP_BASE_URL), then
GETs category/article HTML and parses window.initialData.

Usage, from services/backstop-mcp:
  uv run python agent-explore/docs.py tree
  uv run python agent-explore/docs.py category 21
  uv run python agent-explore/docs.py article 941
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError

SSO_START = "https://help-prod.backstopsolutions.com/backstop/sso/elevioStart.jsp"
SSO_LOGIN = "https://help-prod.backstopsolutions.com/backstop/sso/j_security_check"
SSO_TOKEN = "https://help-prod.backstopsolutions.com/backstop/sso/elevioToken.jsp"
KB_ORIGIN = "https://backstopsolutions.elevio.help"
KB_HOST = "backstopsolutions.elevio.help"
TIMEOUT = 120.0

_JSON_OBJECT: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])
_JSON_LIST: TypeAdapter[list[object]] = TypeAdapter(list[object])


class _Args(argparse.Namespace):
    cmd: str
    refresh: bool
    id: str

    def __init__(self) -> None:
        super().__init__()
        self.cmd = ""
        self.refresh = False
        self.id = ""


def _env_file() -> Path:
    return Path(__file__).resolve().parent / ".env"


def _cache_dir() -> Path:
    path = Path(__file__).resolve().parent / ".docs-cache"
    path.mkdir(exist_ok=True)
    return path


def _as_object(value: object) -> dict[str, object]:
    return _JSON_OBJECT.validate_python(value)


def _as_list(value: object) -> list[object]:
    return _JSON_LIST.validate_python(value)


def _object_or_none(value: object) -> dict[str, object] | None:
    try:
        return _as_object(value)
    except ValidationError:
        return None


def _objects(value: object) -> list[dict[str, object]]:
    try:
        items = _as_list(value)
    except ValidationError:
        return []
    out: list[dict[str, object]] = []
    for item in items:
        parsed = _object_or_none(item)
        if parsed is not None:
            out.append(parsed)
    return out


def _load_json_object(path: Path) -> dict[str, object]:
    return _JSON_OBJECT.validate_json(path.read_text())


def _cookie_field(cookie: dict[str, object], key: str, fallback: str) -> str:
    value = cookie.get(key)
    return value if isinstance(value, str) else fallback


def _require_docs_credentials() -> tuple[str, str]:
    load_dotenv(_env_file())
    username = os.environ.get("BACKSTOP_DOCS_USERNAME") or os.environ.get(
        "BACKSTOP_SERVICE_USERNAME", ""
    )
    password = os.environ.get("BACKSTOP_DOCS_PASSWORD", "")
    if not username or not password:
        raise SystemExit(
            "Elevio docs need a web login, not the API token. Set "
            + "BACKSTOP_DOCS_USERNAME and BACKSTOP_DOCS_PASSWORD in "
            + "services/backstop-mcp/agent-explore/.env (username may fall back to "
            + "BACKSTOP_SERVICE_USERNAME)."
        )
    return username, password


def decode_js_string(src: str) -> str:
    quote = src[0]
    i = 1
    out: list[str] = []
    while i < len(src):
        ch = src[i]
        if ch == "\\":
            nxt = src[i + 1]
            mapping = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", "'": "'", '"': '"', "/": "/"}
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
            if nxt == "u" and i + 5 < len(src):
                out.append(chr(int(src[i + 2 : i + 6], 16)))
                i += 6
                continue
            out.append(nxt)
            i += 2
            continue
        if ch == quote:
            return "".join(out)
        out.append(ch)
        i += 1
    raise ValueError("unterminated JS string")


def parse_initial_data(html: str) -> dict[str, object]:
    match = re.search(r"window\.initialData\s*=\s*JSON\.parse\(", html)
    if match is None:
        raise ValueError("page has no window.initialData (not logged in, or Elevio changed)")
    return _as_object(_JSON_OBJECT.validate_json(decode_js_string(html[match.end() :].lstrip())))


def html_to_text(raw: str) -> str:
    without_noise = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", raw, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", without_noise))
    return re.sub(r"\s+", " ", text).strip()


def _article_stub(article: dict[str, object]) -> dict[str, object]:
    category = _object_or_none(article.get("category"))
    return {
        "id": article.get("id"),
        "title": article.get("title"),
        "slug": article.get("slug"),
        "summary": article.get("summary"),
        "category_id": None if category is None else category.get("id"),
    }


def _summarize_category(data: dict[str, object]) -> dict[str, object]:
    page = _object_or_none(data.get("page"))
    if page is None:
        raise ValueError("initialData.page missing")
    payload = _object_or_none(page.get("data"))
    category = None if payload is None else _object_or_none(payload.get("category"))
    if category is None:
        raise ValueError("category payload missing")
    articles_block = _object_or_none(category.get("articles")) or {}
    return {
        "id": category.get("id"),
        "title": category.get("title"),
        "slug": category.get("slug"),
        "page_info": articles_block.get("pageInfo"),
        "subcategories": [
            {"id": item.get("id"), "title": item.get("title"), "slug": item.get("slug")}
            for item in _objects(category.get("subCategories"))
        ],
        "articles": [_article_stub(item) for item in _objects(articles_block.get("results"))],
    }


def _summarize_article(data: dict[str, object]) -> dict[str, object]:
    page = _object_or_none(data.get("page"))
    if page is None:
        raise ValueError("initialData.page missing")
    payload = _object_or_none(page.get("data"))
    article = None if payload is None else _object_or_none(payload.get("article"))
    if article is None:
        raise ValueError("article payload missing")
    body_text = article.get("bodyText")
    if not isinstance(body_text, str) or not body_text.strip():
        body = article.get("body")
        body_text = html_to_text(body) if isinstance(body, str) else ""
    related = None if payload is None else payload.get("relatedArticles")
    return {
        **_article_stub(article),
        "body_text": body_text,
        "related": [_article_stub(item) for item in _objects(related)],
    }


def _summarize_tree(data: dict[str, object]) -> list[dict[str, object]]:
    tree = _object_or_none(data.get("categoryTree"))
    if tree is None:
        return []

    def walk(nodes: object) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for node in _objects(nodes):
            kids = node.get("subCategories")
            if kids is None:
                kids = node.get("categories")
            out.append(
                {
                    "id": node.get("id"),
                    "title": node.get("title"),
                    "slug": node.get("slug"),
                    "children": walk(kids),
                }
            )
        return out

    return walk(tree.get("categories"))


def _session_path() -> Path:
    return _cache_dir() / "session.json"


def _save_session(client: httpx.Client) -> None:
    cookies: list[dict[str, object]] = [
        {"name": cookie.name, "value": cookie.value, "domain": cookie.domain, "path": cookie.path}
        for cookie in client.cookies.jar
    ]
    _session_path().write_text(json.dumps(cookies))


def _load_session(client: httpx.Client) -> None:
    path = _session_path()
    if not path.exists():
        return
    try:
        cookies = _JSON_LIST.validate_json(path.read_text())
    except ValueError:
        return
    for raw in cookies:
        cookie = _object_or_none(raw)
        if cookie is None:
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if isinstance(name, str) and isinstance(value, str):
            client.cookies.set(
                name,
                value,
                domain=_cookie_field(cookie, "domain", ""),
                path=_cookie_field(cookie, "path", "/"),
            )


def _still_login_form(html: str) -> bool:
    return "j_security_check" in html and "j_password" in html


def _on_elevio(url: httpx.URL | str) -> bool:
    return urlparse(str(url)).netloc == KB_HOST


def _elevio_redirect_url(html: str) -> str | None:
    urls = re.findall(r"https://backstopsolutions\.elevio\.help[^\"'\s<>]+", html)
    return urls[0] if urls else None


def _follow_elevio_bounce(client: httpx.Client, current: httpx.Response) -> httpx.Response:
    bounce = _elevio_redirect_url(current.text)
    if bounce is None:
        token_page = client.get(SSO_TOKEN, follow_redirects=True)
        bounce = _elevio_redirect_url(token_page.text)
        current = token_page
    if bounce is not None:
        return client.get(bounce, follow_redirects=True)
    return current


def _login(client: httpx.Client, username: str, password: str) -> None:
    start = client.get(SSO_START, follow_redirects=True)
    if start.status_code != 200:
        raise SystemExit(f"SSO start failed: HTTP {start.status_code}")
    current = start
    if not _on_elevio(current.url):
        response = client.post(
            SSO_LOGIN,
            data={"j_username": username, "j_password": password},
            follow_redirects=True,
        )
        if _still_login_form(response.text):
            raise SystemExit(
                "Elevio SSO login failed (check BACKSTOP_DOCS_USERNAME / BACKSTOP_DOCS_PASSWORD)."
            )
        current = response
        if not _on_elevio(current.url):
            current = _follow_elevio_bounce(client, current)
    if not _on_elevio(current.url):
        raise SystemExit("Elevio SSO did not reach the help center.")
    _save_session(client)


@contextmanager
def _client_with_session() -> Generator[httpx.Client]:
    username, password = _require_docs_credentials()
    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"user-agent": "Mozilla/5.0 backstop-mcp-docs-explorer"},
    ) as client:
        _load_session(client)
        probe = client.get(f"{KB_ORIGIN}/en/categories/21")
        if (
            probe.status_code == 401
            or _still_login_form(probe.text)
            or "JSON.parse(" not in probe.text
        ):
            _login(client, username, password)
        yield client


def _cache_write(name: str, payload: dict[str, object]) -> None:
    (_cache_dir() / f"{name}.json").write_text(json.dumps(payload, indent=2))


def _fetch_html(client: httpx.Client, path: str) -> str:
    response = client.get(f"{KB_ORIGIN}{path}")
    if response.status_code == 401 or _still_login_form(response.text):
        raise SystemExit(
            "Elevio session expired; delete "
            + "services/backstop-mcp/agent-explore/.docs-cache/session.json and retry."
        )
    if response.status_code != 200:
        raise SystemExit(f"GET {path} failed: HTTP {response.status_code}")
    return response.text


def cmd_tree(*, refresh: bool) -> dict[str, object]:
    cache = _cache_dir() / "tree.json"
    if cache.exists() and not refresh:
        return _load_json_object(cache)
    with _client_with_session() as client:
        html = _fetch_html(client, "/en/categories/21")
        payload: dict[str, object] = {"categories": _summarize_tree(parse_initial_data(html))}
    _cache_write("tree", payload)
    return payload


def cmd_category(category_id: str, *, refresh: bool) -> dict[str, object]:
    cache_name = f"category-{category_id}"
    cache = _cache_dir() / f"{cache_name}.json"
    if cache.exists() and not refresh:
        return _load_json_object(cache)
    with _client_with_session() as client:
        html = _fetch_html(client, f"/en/categories/{category_id}")
        payload = _summarize_category(parse_initial_data(html))
    _cache_write(cache_name, payload)
    return payload


def cmd_article(article_id: str, *, refresh: bool) -> dict[str, object]:
    cache_name = f"article-{article_id}"
    cache = _cache_dir() / f"{cache_name}.json"
    if cache.exists() and not refresh:
        return _load_json_object(cache)
    with _client_with_session() as client:
        html = _fetch_html(client, f"/en/articles/{article_id}")
        payload = _summarize_article(parse_initial_data(html))
    _cache_write(cache_name, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Read Backstop Elevio product docs.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def with_refresh(subparser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        subparser.add_argument(
            "--refresh", action="store_true", help="ignore .docs-cache and re-fetch"
        )
        return subparser

    with_refresh(sub.add_parser("tree", help="list the help-center category tree"))
    category = with_refresh(sub.add_parser("category", help="list articles in one category"))
    category.add_argument("id")
    article = with_refresh(sub.add_parser("article", help="fetch one article body"))
    article.add_argument("id")
    args = parser.parse_args(namespace=_Args())
    if args.cmd == "tree":
        payload = cmd_tree(refresh=args.refresh)
    elif args.cmd == "category":
        payload = cmd_category(args.id, refresh=args.refresh)
    else:
        payload = cmd_article(args.id, refresh=args.refresh)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
