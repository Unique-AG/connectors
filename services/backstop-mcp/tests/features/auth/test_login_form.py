from backstop_mcp.features.auth.login_form import render_login_form


class TestRenderLoginForm:
    def test_includes_request_id_as_hidden_field(self) -> None:
        html = render_login_form("req-123", "csrf-abc")

        assert 'name="request_id" value="req-123"' in html

    def test_prefills_username_but_never_a_token(self) -> None:
        html = render_login_form("req-123", "csrf-abc", username="bob.smith")

        assert 'value="bob.smith"' in html
        assert 'type="password"' in html

    def test_shows_error_when_provided(self) -> None:
        html = render_login_form("req-123", "csrf-abc", error="Invalid username or API token.")

        assert "Invalid username or API token." in html

    def test_omits_error_block_when_no_error(self) -> None:
        html = render_login_form("req-123", "csrf-abc")

        assert 'class="error"' not in html

    def test_escapes_untrusted_client_name(self) -> None:
        html = render_login_form("req-123", "csrf-abc", client_name="<script>alert(1)</script>")

        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_escapes_untrusted_username(self) -> None:
        html = render_login_form("req-123", "csrf-abc", username='"><script>alert(1)</script>')

        assert "<script>" not in html

    def test_escapes_untrusted_error_message(self) -> None:
        html = render_login_form("req-123", "csrf-abc", error="<script>alert(1)</script>")

        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_escapes_request_id(self) -> None:
        html = render_login_form('req"><script>alert(1)</script>', "csrf-abc")

        assert "<script>" not in html

    def test_uses_unique_backstop_mcp_title(self) -> None:
        html = render_login_form("req-123", "csrf-abc")

        assert "<title>Unique Backstop Mcp</title>" in html
        assert "<h1>Unique Backstop Mcp</h1>" in html

    def test_labels_token_field_as_api_token(self) -> None:
        html = render_login_form("req-123", "csrf-abc")

        assert 'for="api_token">API token</label>' in html
        assert ">Password<" not in html

    def test_explains_how_to_get_an_api_token(self) -> None:
        html = render_login_form("req-123", "csrf-abc")

        assert "How to get an API token" in html
        assert "Generate New Token" in html
        assert "https://backstopsolutions.elevio.help/en/articles/236" in html

    def test_includes_csrf_token_as_hidden_field(self) -> None:
        """The other half of the double-submit check in `login_csrf.py`."""
        html = render_login_form("req-123", "csrf-abc")

        assert 'name="csrf_token" value="csrf-abc"' in html

    def test_escapes_csrf_token(self) -> None:
        html = render_login_form("req-123", '"><script>alert(1)</script>')

        assert "<script>" not in html
