from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_PROFILE_INSTRUCTIONS = "Main Menu > System Tools > Administrative > Update Your Profile"
_DOCS_URL = "https://backstopsolutions.elevio.help/en/articles/236"

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
    """Render the HTML login form collecting a Backstop username + personal API token.

    `request_id` identifies the pending `PendingAuthorization` row (see `db/models.py`) this
    submission belongs to; it's carried as a hidden field and round-tripped by the POST handler
    in `auth/provider.py`. `csrf_token` is the other half of the double-submit check in
    `auth/login_csrf.py` — required, not optional, so a new render path can't quietly ship a
    form the POST handler will reject. `username` is re-filled on a failed attempt so the user
    doesn't have to retype it — the API token never is. Values are autoescaped by Jinja2 since
    `client_name` comes from a dynamically-registered (and therefore untrusted) OAuth client.
    """
    return _ENV.get_template("login.html").render(
        request_id=request_id,
        csrf_token=csrf_token,
        client_name=client_name,
        username=username,
        error=error,
        profile_instructions=_PROFILE_INSTRUCTIONS,
        docs_url=_DOCS_URL,
    )
