from mcp_credential_auth import RedirectTarget

from with_intelligence_mcp.features.auth.login_form import render_login_form

_CLAUDE = RedirectTarget(host="claude.ai", on_this_device=False)


class TestRenderLoginForm:
    def test_names_the_host_the_login_is_sent_to(self) -> None:
        html = render_login_form("req-123", "csrf-abc", _CLAUDE, client_name="Claude")

        assert "Claude wants to connect to your With Intelligence account." in html
        assert "you will be sent to <strong>claude.ai</strong>." in html
        assert "Not the app you started this from? Close this page" in html

    def test_says_a_private_use_scheme_is_an_app_on_this_computer(self) -> None:
        target = RedirectTarget(host="cursor://anysphere.cursor-mcp", on_this_device=True)

        html = render_login_form("req-123", "csrf-abc", target)

        assert "<strong>cursor://anysphere.cursor-mcp</strong>, an app on this computer." in html

    def test_escapes_the_redirect_host_and_client_name(self) -> None:
        target = RedirectTarget(host="<script>alert(1)</script>", on_this_device=False)

        html = render_login_form("req-123", "csrf-abc", target, client_name="<b>Claude</b>")

        assert "<script>" not in html
        assert "<b>Claude</b>" not in html
        assert "&lt;script&gt;" in html
