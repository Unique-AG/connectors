from mcp_credential_auth import LoginCsrf

_login_csrf = LoginCsrf("backstop_login_csrf_")

csrf_cookie_name = _login_csrf.cookie_name
issue_csrf_token = _login_csrf.issue_token
set_csrf_cookie = _login_csrf.set_cookie
clear_csrf_cookie = _login_csrf.clear_cookie
csrf_token_is_valid = _login_csrf.token_is_valid

__all__ = [
    "clear_csrf_cookie",
    "csrf_cookie_name",
    "csrf_token_is_valid",
    "issue_csrf_token",
    "set_csrf_cookie",
]
