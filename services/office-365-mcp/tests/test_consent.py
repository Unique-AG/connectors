from urllib.parse import parse_qs, urlsplit

from office_365_mcp.config import ToolsPreset
from office_365_mcp.server import admin_consent_url
from office_365_mcp.tools import resolve

_REDIRECT_URI = "https://www.unique.ai/setup/consent-completed/entra-id"


class TestAdminConsentUrl:
    def test_it_asks_for_exactly_the_selected_scopes(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        url = admin_consent_url(
            tenant_id="organizations",
            client_id="client-id",
            selection=selection,
            redirect_uri=_REDIRECT_URI,
        )

        parts = urlsplit(url)
        assert parts.netloc == "login.microsoftonline.com"
        assert parts.path == "/organizations/v2.0/adminconsent"
        assert parse_qs(parts.query) == {
            "client_id": ["client-id"],
            "scope": [" ".join(selection.graph_scopes)],
            "redirect_uri": [_REDIRECT_URI],
        }

    def test_it_escapes_spaces_as_percent_20(self) -> None:
        selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

        url = admin_consent_url(
            tenant_id="organizations",
            client_id="client-id",
            selection=selection,
            redirect_uri=_REDIRECT_URI,
        )

        assert "+" not in url
        assert "%20" in url
