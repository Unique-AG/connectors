from __future__ import annotations

from fastmcp.dependencies import CurrentAccessToken
from fastmcp.server.auth import AccessToken

USER_ID_CLAIM = "sub"
COMPANY_ID_CLAIM = "urn:zitadel:iam:user:resourceowner:id"


def get_user_id(
    token: AccessToken = CurrentAccessToken(),  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
) -> str:
    return _get_required_claim(token, USER_ID_CLAIM)


def get_company_id(
    token: AccessToken = CurrentAccessToken(),  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
) -> str:
    return _get_required_claim(token, COMPANY_ID_CLAIM)


def _get_required_claim(token: AccessToken, claim_name: str) -> str:
    claim_value = token.claims.get(claim_name)
    if not isinstance(claim_value, str) or not claim_value:
        print(f"[q-bridge-mcp] JWT claims: {token.claims}")
        raise ValueError(f"Authenticated token is missing the '{claim_name}' claim")

    return claim_value
