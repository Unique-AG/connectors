import html

_PROFILE_INSTRUCTIONS = (
    "Main Menu > System Tools > Administrative > Update Your Profile > API Security"
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
    doesn't have to retype it — the API token never is. All values are HTML-escaped since
    `client_name` comes from a dynamically-registered (and therefore untrusted) OAuth client.
    """
    safe_request_id = html.escape(request_id, quote=True)
    safe_csrf_token = html.escape(csrf_token, quote=True)
    safe_username = html.escape(username, quote=True)
    client_label = f"{html.escape(client_name)} wants to connect to" if client_name else "Connect"

    error_html = ""
    if error:
        error_html = f'<p class="error">{html.escape(error)}</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Connect Backstop</title>
  <style>
    body {{
      font-family: system-ui, sans-serif; max-width: 420px; margin: 4rem auto; padding: 0 1rem;
    }}
    label {{ display: block; margin-top: 1rem; font-weight: 600; }}
    input {{ width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box; }}
    button {{ margin-top: 1.5rem; padding: 0.6rem 1.2rem; }}
    .error {{ color: #b00020; }}
    .hint {{ color: #555; font-size: 0.9rem; margin-top: 1.5rem; }}
  </style>
</head>
<body>
  <h1>{client_label} your Backstop account</h1>
  {error_html}
  <form method="post">
    <input type="hidden" name="request_id" value="{safe_request_id}">
    <input type="hidden" name="csrf_token" value="{safe_csrf_token}">
    <label for="username">Backstop username</label>
    <input type="text" id="username" name="username" value="{safe_username}"
           autocomplete="username" required>
    <label for="api_token">Backstop API token</label>
    <input type="password" id="api_token" name="api_token" autocomplete="current-password" required>
    <button type="submit">Connect</button>
  </form>
  <p class="hint">
    Don't have a token? Generate one from your Backstop profile:
    {html.escape(_PROFILE_INSTRUCTIONS)}
  </p>
</body>
</html>
"""
