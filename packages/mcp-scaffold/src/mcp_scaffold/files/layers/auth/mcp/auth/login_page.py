"""The page a user signs in on, and the cookie that proves the form came from it."""

import hashlib
import hmac
from pathlib import Path
import secrets

from jinja2 import Environment
from jinja2 import FileSystemLoader
from starlette.requests import Request
from starlette.responses import HTMLResponse

_PAGES = Environment(loader=FileSystemLoader(Path(__file__).parent / "pages"), autoescape=True)
_CSRF_COOKIE_PREFIX = "mcp_sign_in_"
# The page holds a password field: no cache, no referrer, no frame.
_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def login_page(
    *,
    title: str,
    request_id: str,
    csrf_token: str,
    username: str = "",
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    html = _PAGES.get_template("login.html").render(
        title=title, request_id=request_id, csrf_token=csrf_token, username=username, error=error
    )
    return HTMLResponse(html, status_code=status_code, headers=_HEADERS)


def message_page(*, title: str, message: str, status_code: int) -> HTMLResponse:
    html = _PAGES.get_template("message.html").render(title=title, message=message)
    return HTMLResponse(html, status_code=status_code, headers=_HEADERS)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_cookie(request_id: str) -> str:
    """One cookie per sign-in, so two open at once do not replace each other's."""
    return _CSRF_COOKIE_PREFIX + hashlib.sha256(request_id.encode()).hexdigest()[:16]


def csrf_token_matches(request: Request, request_id: str, submitted: str) -> bool:
    """The double-submit check: the form's token is the one in the cookie the page set."""
    expected = request.cookies.get(csrf_cookie(request_id))
    return expected is not None and hmac.compare_digest(expected, submitted)
