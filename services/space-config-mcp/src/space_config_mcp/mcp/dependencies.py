from collections.abc import Callable
import logging
import os
from typing import cast

from fastmcp.dependencies import CurrentContext
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context

from space_config_mcp.persistence import Persistence
from space_config_mcp.upstream import Upstream

_LOG = logging.getLogger(__name__)

_get_request_meta: Callable[[], dict[str, object] | None] | None = None
_user_id_key: str | None = None
_company_id_key: str | None = None
_assistant_id_key: str | None = None

try:
    from unique_mcp.meta.keys import MetaKeys as _MetaKeys
    from unique_mcp.unique_injectors import get_request_meta as _get_request_meta_impl

    _get_request_meta = _get_request_meta_impl
    _user_id_key = _MetaKeys.USER_ID
    _company_id_key = _MetaKeys.COMPANY_ID
    _assistant_id_key = _MetaKeys.ASSISTANT_ID
    _LOG.info(
        "auth: _meta injector available — user_id_key=%r company_id_key=%r assistant_id_key=%r",
        _user_id_key,
        _company_id_key,
        _assistant_id_key,
    )
except ImportError:
    _LOG.warning("auth: unique_mcp not installed — _meta injection unavailable")


def get_upstream(ctx: Context = CurrentContext()) -> Upstream:
    return cast(Upstream, ctx.lifespan_context["upstream"])


def get_persistence(ctx: Context = CurrentContext()) -> Persistence:
    return cast(Persistence, ctx.lifespan_context["persistence"])


def _auth_configured() -> bool:
    """True when Zitadel OIDC is configured — _meta values are then verified by the auth layer."""
    return bool(os.environ.get("ZITADEL_BASE_URL"))


async def get_caller() -> tuple[str, str]:
    """Resolve (user_id, company_id) for the current request.

    Priority:
    1. ``_meta`` keys injected by the Unique platform per tool call.
       When Zitadel is configured the auth layer already verified the token;
       without it the values are trusted as-is (dev / platform-registered mode).
    2. ``UNIQUE_AUTH_USER_ID`` / ``UNIQUE_AUTH_COMPANY_ID`` env vars (pure local dev).
    """
    auth_configured = _auth_configured()
    _LOG.info(
        "get_caller: auth_configured=%s meta_injector=%s user_id_key=%r company_id_key=%r",
        auth_configured,
        _get_request_meta is not None,
        _user_id_key,
        _company_id_key,
    )

    if _get_request_meta is not None and _user_id_key is not None and _company_id_key is not None:
        meta = _get_request_meta()
        _LOG.info(
            "get_caller: _meta present=%s keys=%s",
            meta is not None,
            sorted(meta.keys()) if meta is not None else [],
        )
        if meta is not None:
            uid = meta.get(_user_id_key)
            cid = meta.get(_company_id_key)
            if uid and isinstance(uid, str) and cid and isinstance(cid, str):
                _LOG.info("get_caller: resolved via _meta (auth_configured=%s)", auth_configured)
                return uid, cid
            _LOG.warning(
                "get_caller: _meta present but user_id/company_id keys missing or wrong type "
                "(uid=%r cid=%r); falling back to env vars",
                type(uid).__name__,
                type(cid).__name__,
            )

    allow_ephemeral = os.environ.get("ALLOW_EPHEMERAL_OAUTH_STORAGE", "").lower() == "true"
    _LOG.info("get_caller: ALLOW_EPHEMERAL_OAUTH_STORAGE=%s", allow_ephemeral)
    if allow_ephemeral:
        uid = os.environ.get("UNIQUE_AUTH_USER_ID")
        cid = os.environ.get("UNIQUE_AUTH_COMPANY_ID")
        _LOG.info("get_caller: env vars uid_set=%s cid_set=%s", uid is not None, cid is not None)
        if uid and cid:
            _LOG.info("get_caller: resolved via env vars")
            return uid, cid

    raise ToolError(
        "Cannot resolve caller identity. "
        f"auth_configured={auth_configured}, "
        f"meta_injector={'available' if _get_request_meta is not None else 'missing'}, "
        f"ALLOW_EPHEMERAL_OAUTH_STORAGE={os.environ.get('ALLOW_EPHEMERAL_OAUTH_STORAGE', 'unset')!r}. "
        "Set UNIQUE_AUTH_USER_ID / UNIQUE_AUTH_COMPANY_ID or register via Zitadel."
    )


async def get_space_id(
    caller: tuple[str, str] = Depends(get_caller),
    upstream: Upstream = Depends(get_upstream),
) -> str:
    """Resolve the calling space's assistant ID from request meta.

    The Unique platform injects the assistant ID into every tool call's ``_meta``.
    When Zitadel is configured the space is verified against the authenticated company.
    Without Zitadel the value is trusted as-is (dev / platform-registered mode).
    Falls back to ``UNIQUE_AUTH_ASSISTANT_ID`` when _meta has no assistant ID.
    """
    auth_configured = _auth_configured()

    if _get_request_meta is not None and _assistant_id_key is not None:
        meta = _get_request_meta()
        if meta is not None:
            aid = meta.get(_assistant_id_key)
            _LOG.info(
                "get_space_id: _meta assistant_id present=%s auth_configured=%s",
                bool(aid),
                auth_configured,
            )
            if aid and isinstance(aid, str):
                if auth_configured:
                    user_id, company_id = caller
                    try:
                        await upstream.get_space(user_id, company_id, aid)
                    except Exception as exc:
                        raise ToolError("Space not found or not accessible.") from exc
                _LOG.info("get_space_id: resolved via _meta: %s", aid)
                return aid

    allow_ephemeral = os.environ.get("ALLOW_EPHEMERAL_OAUTH_STORAGE", "").lower() == "true"
    if allow_ephemeral:
        aid = os.environ.get("UNIQUE_AUTH_ASSISTANT_ID")
        if aid:
            _LOG.info("get_space_id: resolved via env var: %s", aid)
            return aid

    raise ToolError(
        "Cannot resolve space ID. "
        f"auth_configured={auth_configured}, "
        f"meta_injector={'available' if _get_request_meta is not None else 'missing'}, "
        f"ALLOW_EPHEMERAL_OAUTH_STORAGE={os.environ.get('ALLOW_EPHEMERAL_OAUTH_STORAGE', 'unset')!r}. "
        "Set UNIQUE_AUTH_ASSISTANT_ID or register via Zitadel."
    )
