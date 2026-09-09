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
    """Render the form collecting a With Intelligence username and password.

    `request_id` identifies the pending authorization and is round-tripped as a hidden field.
    `csrf_token` is required rather than optional, so a new render path cannot quietly ship a
    form the POST handler will reject. `username` is re-filled after a failure; the password
    never is. Values are autoescaped because `client_name` comes from a dynamically-registered,
    and therefore untrusted, OAuth client.
    """
    return _ENV.get_template("login.html").render(
        request_id=request_id,
        csrf_token=csrf_token,
        client_name=client_name,
        username=username,
        error=error,
        docs_url=_DOCS_URL,
    )
