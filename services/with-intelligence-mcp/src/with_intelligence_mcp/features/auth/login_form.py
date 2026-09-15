from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_DOCS_URL = "https://withapi.readme.io/docs/getting-started"

_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=select_autoescape(enabled_extensions=("html", "xml")),
)


def render_login_form(
    request_id: str,
    csrf_token: str,
    *,
    client_name: str | None = None,
    username: str = "",
    error: str | None = None,
) -> str:
    """Render the WI login form."""
    return _ENV.get_template("login.html").render(
        request_id=request_id,
        csrf_token=csrf_token,
        client_name=client_name,
        username=username,
        error=error,
        docs_url=_DOCS_URL,
    )
