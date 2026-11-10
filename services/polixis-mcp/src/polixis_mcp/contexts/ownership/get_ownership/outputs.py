from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.risks import RISK_COUNTS_DESCRIPTION
from polixis_mcp.contexts.risks import RISK_MARKERS_DESCRIPTION

FLAGGED_SHOWN = 25


class ChainLink(BaseModel):
    """One link of an ownership chain."""

    pid: str = Field(description="The entity at this link.")
    name: str | None = Field(description="Its name, null when Polixis gives none.")
    share_percent: float | None = Field(
        description="The share across this link, with the link before it or, for the first, "
        "with the entity asked about; null when Polixis reports none."
    )


class OwnershipEntity(BaseModel):
    """An entity in the ownership tree, with every chain that reaches it added up."""

    pid: str = Field(description="The entity's pid.")
    name: str | None = Field(description="Its name, in English where Polixis has one.")
    entity_type: str | None = Field(description="PERSON or ORGANIZATION.")
    effective_share_percent: float | None = Field(
        description=(
            "Computed by this MCP, not sent by Polixis, which reports only the share on each "
            "link: the shares along each chain between it and the entity asked about "
            "multiplied together (50% of 60% is 30%), then summed over the chains. A chain "
            "with a link that reports no share is left out. For owners it is the share it "
            "holds, for holdings the share held in it. Null when no chain reports a share on "
            "every link. Call it a figure derived from Polixis's link shares, not Polixis's own."
        )
    )
    share_unknown_on_some_chain: bool = Field(
        description="Whether a chain to it has a link without a share, so the true effective "
        "share may be higher."
    )
    direct_share_percent: float | None = Field(
        description="The share across its own direct link with the entity asked about; null "
        "when it has none or Polixis reports no share."
    )
    depth: int = Field(description="Fewest links from the entity asked about: 1 is direct.")
    chains: int = Field(description="How many distinct chains of links reach it.")
    roles: list[str] = Field(description="Its roles across its links, such as shareholder.")
    end_of_chain: bool = Field(
        description=(
            "Whether nothing lies beyond it: for owners, no owner of its own is known, as for "
            "an ultimate beneficial owner; for holdings, it holds nothing further. A tree cut "
            "short by Polixis may hide more."
        )
    )
    flags: list[str] = Field(description="Such as SANCTION, PEP or REP.")
    alerts: list[str] = Field(description="Alert categories, such as STATECO or RESTRICTION.")
    strongest_chain: list[ChainLink] = Field(
        description="The chain carrying the largest share, from the link next to the entity "
        "asked about to this entity."
    )


class OwnershipFlag(BaseModel):
    """A flagged entity of the tree, wherever its rows fall."""

    pid: str = Field(description="The entity's pid.")
    name: str | None = Field(description="Its name, null when Polixis gives none.")
    effective_share_percent: float | None = Field(
        description="As on its entity row: computed by this MCP from the link shares, not sent "
        "by Polixis; null when no chain reports a share on every link."
    )
    depth: int = Field(description="Fewest links from the entity asked about.")
    risks: list[str] = Field(description=RISK_MARKERS_DESCRIPTION)


class OwnershipPage(BaseModel):
    """The entities of an ownership tree, the largest effective share first, one page of them."""

    pid: str = Field(description="The entity asked about.")
    total_entities: int = Field(description="Entities across every page.")
    total_share_unknown: int = Field(
        description=(
            "Entities across every page with `share_unknown_on_some_chain`, whose true share may "
            "be higher than shown. Those with no known share at all come last, so shares "
            "falling below a threshold settle it only once every one of these has been read."
        )
    )
    truncated_by_polixis: bool = Field(
        description=(
            "Whether Polixis cut the tree at its cap of 300 nodes per level or 5,000 in all, so "
            "even every page together is not the whole tree. Start again from a sub-holding."
        )
    )
    total_flagged: int = Field(description="Flagged entities in the whole tree.")
    total_by_risk: dict[str, int] = Field(description=RISK_COUNTS_DESCRIPTION)
    flagged: list[OwnershipFlag] = Field(
        description=(
            f"At most {FLAGGED_SHOWN} flagged entities of the whole tree, the sanctioned "
            "first, then in the order of the rows; on the first page only, empty on the "
            "others. When `total_flagged` is larger, the rest carry their flags on their "
            "entity rows, further down the pages."
        )
    )
    entities: list[OwnershipEntity] = Field(description="The entities of this page.")
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; null on the last page."
    )
