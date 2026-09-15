from starlette.requests import Request
from starlette.responses import Response

from mcp_credential_auth import LoginCsrf


def _request(cookie_name: str, token: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"cookie", f"{cookie_name}={token}".encode())],
        }
    )


class TestLoginCsrf:
    def test_scopes_cookie_names_to_the_service_and_request(self) -> None:
        backstop = LoginCsrf("backstop_login_csrf_")
        wi = LoginCsrf("wi_login_csrf_")

        assert backstop.cookie_name("request-1").startswith("backstop_login_csrf_")
        assert wi.cookie_name("request-1").startswith("wi_login_csrf_")
        assert backstop.cookie_name("request-1") != backstop.cookie_name("request-2")

    def test_accepts_matching_cookie_and_submitted_tokens(self) -> None:
        csrf = LoginCsrf("login_csrf_")
        cookie_name = csrf.cookie_name("request-1")
        request = _request(cookie_name, "matching-token")

        assert csrf.token_is_valid(request, "request-1", "matching-token")

    def test_rejects_missing_or_mismatched_tokens(self) -> None:
        csrf = LoginCsrf("login_csrf_")
        cookie_name = csrf.cookie_name("request-1")
        request = _request(cookie_name, "cookie-token")

        assert not csrf.token_is_valid(request, "request-1", "")
        assert not csrf.token_is_valid(request, "request-1", "submitted-token")

    def test_sets_and_clears_the_same_cookie(self) -> None:
        csrf = LoginCsrf("login_csrf_")
        response = Response()

        csrf.set_cookie(
            response,
            "request-1",
            "token",
            path="/login",
            max_age_seconds=600,
            secure=True,
        )
        csrf.clear_cookie(response, "request-1", path="/login", secure=True)

        headers = response.headers.getlist("set-cookie")
        assert len(headers) == 2
        assert all(csrf.cookie_name("request-1") in header for header in headers)
