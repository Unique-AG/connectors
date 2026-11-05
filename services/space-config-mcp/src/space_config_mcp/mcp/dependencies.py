from collections.abc import Callable
import os
from typing import cast

from fastmcp.dependencies import CurrentContext
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context

from space_config_mcp.persistence import Persistence
from space_config_mcp.upstream import Upstream

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
except ImportError:
    pass


def get_upstream(ctx: Context = CurrentContext()) -> Upstream:
    return cast(Upstream, ctx.lifespan_context["upstream"])


def get_persistence(ctx: Context = CurrentContext()) -> Persistence:
    return cast(Persistence, ctx.lifespan_context["persistence"])


async def get_caller() -> tuple[str, str]:
    """Resolve (user_id, company_id) for the current request.

    Priority:
    1. ``_meta`` keys injected by the Unique platform per tool call
    2. ``UNIQUE_AUTH_USER_ID`` / ``UNIQUE_AUTH_COMPANY_ID`` env vars (local dev)
    """
    if _get_request_meta is not None and _user_id_key is not None and _company_id_key is not None:
        meta = _get_request_meta()
        if meta is not None:
            uid = meta.get(_user_id_key)
            cid = meta.get(_company_id_key)
            if uid and isinstance(uid, str) and cid and isinstance(cid, str):
                return uid, cid

    uid = os.environ.get("UNIQUE_AUTH_USER_ID")
    cid = os.environ.get("UNIQUE_AUTH_COMPANY_ID")
    if uid and cid:
        return uid, cid

    raise ToolError(
        "Cannot resolve caller identity: no _meta auth keys and "
        "UNIQUE_AUTH_USER_ID / UNIQUE_AUTH_COMPANY_ID are not set."
    )


async def get_space_id() -> str:
    """Resolve the calling space's assistant ID from request meta.

    The Unique platform injects ``unique.app/chat/assistant-id`` into every
    tool call's ``_meta``. Falls back to ``UNIQUE_AUTH_ASSISTANT_ID`` for
    local development.
    """
    if _get_request_meta is not None and _assistant_id_key is not None:
        meta = _get_request_meta()
        if meta is not None:
            aid = meta.get(_assistant_id_key)
            if aid and isinstance(aid, str):
                return aid

    aid = os.environ.get("UNIQUE_AUTH_ASSISTANT_ID")
    if aid:
        return aid

    raise ToolError(
        "Cannot resolve space ID: no _meta assistant-id key and "
        "UNIQUE_AUTH_ASSISTANT_ID is not set."
    )
