from collections.abc import Iterable

_RISK_FLAGS = frozenset({"SANCTION", "PEP", "FORMER_PEP", "REP"})
_RISK_ALERTS = frozenset({"SANCTION", "SANCTIONTERRITORY", "RESTRICTION", "STATECO"})

RISK_MARKERS_DESCRIPTION = (
    "Its risk markers: the flags SANCTION, PEP, FORMER_PEP or REP, and the alert categories "
    "SANCTION, SANCTIONTERRITORY, RESTRICTION or STATECO (state-owned or -controlled)."
)

RISK_COUNTS_DESCRIPTION = (
    "How many of the flagged entries, across every page, carry each risk marker. Every marker "
    "is listed, so a 0 settles that none carries it without reading the other pages."
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
