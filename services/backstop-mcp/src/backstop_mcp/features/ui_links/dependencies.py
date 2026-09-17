from functools import lru_cache

from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.ui_links.inputs import BackstopLinkTarget
from backstop_mcp.features.ui_links.utils import BuildEntityLinkUtil, ParseEntityLinkUtil


@lru_cache(maxsize=1)
def get_build_entity_link_util_factory() -> BuildEntityLinkUtil:
    return BuildEntityLinkUtil()


@lru_cache(maxsize=1)
def get_parse_entity_link_util_factory() -> ParseEntityLinkUtil:
    return ParseEntityLinkUtil()


def get_effective_ui_base_url() -> str | None:
    return get_backstop_config().effective_ui_base_url


def record_url(target: BackstopLinkTarget) -> str | None:
    """Canonical CRM URL for a published read, or None when this deployment has no UI origin."""
    return get_build_entity_link_util_factory().canonical_url(
        target=target,
        ui_base_url=get_effective_ui_base_url(),
    )
