from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.risks import ALERT_CATEGORIES_DESCRIPTION
from polixis_mcp.contexts.risks import FLAGS_DESCRIPTION
from polixis_mcp.contexts.risks import RISK_COUNTS_DESCRIPTION
from polixis_mcp.contexts.risks import RISK_MARKERS_DESCRIPTION

FLAGGED_SHOWN = 25


class ChainLink(BaseModel):
    """One link of an ownership chain."""

    pid: str = Field(description="The entity at this link.")
    name: str | None = Field(description="Its name, null when Polixis gives none.")
    share_percent: float | None = Field(
        description="Polixis's sharePercent for this link alone, with the link before it or, "
        "for the first, with the entity asked about; null when Polixis reports none or 0."
    )


class OwnershipEntity(BaseModel):
    """An entity in Polixis's ownership tree, with every chain that reaches it added up by this
    MCP.
    """

    pid: str = Field(description="The entity's pid.")
    name: str | None = Field(description="Its name, in English where Polixis has one.")
    entity_type: str | None = Field(
        description="PERSON or ORGANIZATION; vessels and aircraft are organizations."
    )
    effective_share_percent: float | None = Field(
        description=(
            "Computed by this MCP, since Polixis reports only the share on each link: the "
            "shares along each chain between it and the entity asked about multiplied together "
            "(50% of 60% is 30%), then summed over the chains. Polixis may list one entity "
            "twice under the same parent, once per role; that counts once, with the larger "
            "share. A chain with a link that reports no share is left out. For owners it is "
            "the share it holds, for holdings the share held in it. Null when no chain reports "
            "a share on every link. Call it a figure derived from Polixis's link shares, not "
            "Polixis's own."
        )
    )
    share_unknown_on_some_chain: bool = Field(
        description="Computed by this MCP: whether a chain to it has a link Polixis reports no "
        "share for, so the true effective share may be higher."
    )
    direct_share_percent: float | None = Field(
        description="Polixis's sharePercent on its own direct link with the entity asked about; "
        "null when it has none or Polixis reports no share."
    )
    depth: int = Field(
        description="Computed by this MCP: the fewest links between it and the entity asked "
        "about in Polixis's tree; 1 is direct."
    )
    chains: int = Field(
        description="Computed by this MCP: how many distinct chains of links reach it in "
        "Polixis's tree."
    )
    roles: list[str] = Field(
        description="Polixis's roles on its links, such as shareholder, or a role of control "
        "without shares."
    )
    end_of_chain: bool = Field(
        description=(
            "Computed by this MCP: whether nothing lies beyond it in Polixis's tree: for "
            "owners, no owner of its own is known, as for an ultimate beneficial owner; for "
            "holdings, it holds nothing further. A tree cut short by Polixis may hide more."
        )
    )
    flags: list[str] = Field(description=FLAGS_DESCRIPTION)
    alerts: list[str] = Field(description=ALERT_CATEGORIES_DESCRIPTION)
    strongest_chain: list[ChainLink] = Field(
        description="Computed by this MCP: the chain carrying the largest effective share, from "
        "the link next to the entity asked about to this entity."
    )


class OwnershipFlag(BaseModel):
    """A flagged entity of the tree, wherever its rows fall, picked by this MCP."""

    pid: str = Field(description="The entity's pid.")
    name: str | None = Field(description="Its name, null when Polixis gives none.")
    effective_share_percent: float | None = Field(
        description="As on its entity row: computed by this MCP from the link shares, not sent "
        "by Polixis; null when no chain reports a share on every link."
    )
    depth: int = Field(description="As on its entity row: the fewest links to it.")
    risks: list[str] = Field(description=RISK_MARKERS_DESCRIPTION)


class OwnershipPage(BaseModel):
    """The entities of an ownership tree, the largest effective share first, one page of them."""

    pid: str = Field(description="The entity asked about.")
    total_entities: int = Field(
        description="Computed by this MCP: the distinct entities in the tree, across every page."
    )
    total_share_unknown: int = Field(
        description=(
            "Computed by this MCP: entities across every page with "
            "`share_unknown_on_some_chain`, whose true share may be higher than shown. Those "
            "with no known share at all come last, so shares falling below a threshold settle "
            "it only once every one of these has been read."
        )
    )
    truncated_by_polixis: bool = Field(
        description=(
            "Polixis's `truncated`: whether it cut the tree at its cap of 300 nodes per level "
            "or 5,000 in all, so even every page together is not the whole tree. Start again "
            "from a sub-holding."
        )
    )
    total_flagged: int = Field(
        description="Computed by this MCP: entities in the whole tree with a risk marker."
    )
    total_by_risk: dict[str, int] = Field(description=RISK_COUNTS_DESCRIPTION)
    flagged: list[OwnershipFlag] = Field(
        description=(
            f"Computed by this MCP: at most {FLAGGED_SHOWN} entities of the whole tree with a "
            "risk marker, the sanctioned first, then in the order of the rows; on the first "
            "page only, empty on the others. When `total_flagged` is larger, the rest carry "
            "their flags on their entity rows, further down the pages."
        )
    )
    entities: list[OwnershipEntity] = Field(description="The entities of this page.")
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; null on the last page."
    )
