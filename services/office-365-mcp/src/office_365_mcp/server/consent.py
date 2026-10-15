from urllib.parse import quote, urlencode

from office_365_mcp.tools import Selection

__all__ = ["admin_consent_url"]


def admin_consent_url(
    *, tenant_id: str, client_id: str, selection: Selection, redirect_uri: str
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "scope": " ".join(selection.graph_scopes),
            "redirect_uri": redirect_uri,
        },
        quote_via=quote,
    )
    return f"https://login.microsoftonline.com/{tenant_id}/v2.0/adminconsent?{query}"
