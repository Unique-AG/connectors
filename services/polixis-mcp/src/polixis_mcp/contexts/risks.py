from collections.abc import Iterable

from polixis_mcp.contexts.formats import unique
from polixis_mcp.upstream import AlertEntry

_RISK_FLAGS = frozenset({"SANCTION", "PEP", "FORMER_PEP", "REP"})
_RISK_ALERTS = frozenset({"SANCTION", "SANCTIONTERRITORY", "RESTRICTION", "STATECO"})

FLAGS_DESCRIPTION = (
    "Polixis's flags: PEP, a politically exposed person; FORMER_PEP, a PEP Polixis "
    "declassified once 5 years had passed since the function ended; SANCTION, designated on a "
    "sanctions list Polixis covers; DELISTED or DELISTED_ENTITY, designated once and later "
    "delisted; VESSEL or AIRCRAFT, for an organization that is one; REP, which Polixis sends "
    "but its documentation does not define, and which most likely marks reputational risk, as "
    "in its PEP&REP screening."
)

ALERT_CATEGORIES_DESCRIPTION = (
    "Polixis's alert categories of the party itself, such as STATECO (state-owned or "
    "-controlled, or a public body), RESTRICTION (a significant regulatory, legal or business "
    "restriction), SANCTIONTERRITORY (an address in a sanction-sensitive territory), REGULATORY "
    "(such as legal proceedings), CLOSED (liquidated, dissolved or deceased) or LISTED (listed "
    "on a stock exchange)."
)

ALERT_TEXTS_DESCRIPTION = (
    "Polixis's alerts, as it words them: its own, such as a liquidation, legal proceedings or "
    "state ownership, then those it generates from related parties, such as 'Related to a "
    "sanctioned person'. A sanction outside the lists behind the SANCTION flag shows here."
)

RISK_MARKERS_DESCRIPTION = (
    "Computed by this MCP from the party's flags and alerts: the flags SANCTION, PEP, "
    "FORMER_PEP and REP, and the alert categories SANCTION, SANCTIONTERRITORY, RESTRICTION and "
    "STATECO, the ones it carries. Other alerts, such as LISTED or HIGHPROFILE, are not counted "
    "as risks."
)

RISK_COUNTS_DESCRIPTION = (
    "Computed by this MCP: how many of the flagged entries, across every page, carry each risk "
    "marker. Every marker is listed, so a 0 settles that none carries it without reading the "
    "other pages."
)


def risk_markers(*, flags: Iterable[str], alerts: Iterable[str]) -> list[str]:
    """The sanctions, PEP and state-ownership markers among a party's flags and alerts."""
    return sorted({*(_RISK_FLAGS & set(flags)), *(_RISK_ALERTS & set(alerts))})


def risk_counts(markers: Iterable[list[str]]) -> dict[str, int]:
    """How many of the entries carry each marker, every marker included."""
    counts = dict.fromkeys(sorted(_RISK_FLAGS | _RISK_ALERTS), 0)
    for entry in markers:
        for marker in entry:
            counts[marker] += 1
    return counts


def is_hidden_alert(category: str | None) -> bool:
    """Polixis uses `hidden` alerts for its own logic and says to ignore them."""
    return category is not None and category.lower() == "hidden"


def visible_alert_texts(alerts: list[AlertEntry] | None) -> list[str]:
    """The text of each alert but the hidden ones, without repeats."""
    return unique(
        alert.description
        for alert in alerts or []
        if not any(is_hidden_alert(category) for category in alert.type or [])
    )
