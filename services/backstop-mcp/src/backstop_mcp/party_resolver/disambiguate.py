from collections.abc import Sequence
from typing import Protocol, cast

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from mcp.shared.exceptions import McpError
from mcp.types import (
    METHOD_NOT_FOUND,
    ClientCapabilities,
    ElicitationCapability,
)

from backstop_mcp.logging import get_logger
from backstop_mcp.party_resolver.types import (
    NeedsDisambiguation,
    PartyCandidate,
    Resolved,
    ResolvedParty,
    SearchType,
)

logger = get_logger(__name__)


class _ClientCapabilityChecker(Protocol):
    def check_client_capability(self, capability: ClientCapabilities) -> bool: ...


def _unique_label_map(
    candidates: Sequence[PartyCandidate],
) -> tuple[list[str], dict[str, PartyCandidate]]:
    label_to_candidate: dict[str, PartyCandidate] = {}
    unique_labels: list[str] = []
    for candidate in candidates:
        display = candidate.label
        if display in label_to_candidate:
            display = f"{candidate.label} [{candidate.id}]"
            n = 2
            while display in label_to_candidate:
                display = f"{candidate.label} [{candidate.id}] #{n}"
                n += 1
        label_to_candidate[display] = candidate
        unique_labels.append(display)
    assert len(unique_labels) == len(set(unique_labels))
    return unique_labels, label_to_candidate


def _client_supports_elicitation(ctx: Context) -> bool:
    session_obj: object | None = getattr(ctx, "session", None)
    if session_obj is None:
        return True  # tests / no session info — try elicit
    try:
        session = cast(_ClientCapabilityChecker, session_obj)
        return bool(
            session.check_client_capability(ClientCapabilities(elicitation=ElicitationCapability()))
        )
    except Exception as exc:
        logger.warning("party_resolver.disambiguate.capability_check_failed", error=str(exc))
        return True


async def disambiguate_party(
    ctx: Context,
    *,
    candidates: Sequence[PartyCandidate],
    search: str,
    search_type: SearchType,
) -> Resolved | NeedsDisambiguation:
    assert len(candidates) >= 2, "disambiguate_party requires at least two candidates"

    unique_labels, label_to_candidate = _unique_label_map(candidates)
    needs = NeedsDisambiguation(
        candidates=tuple(candidates), search=search, search_type=search_type
    )

    if not _client_supports_elicitation(ctx):
        logger.info(
            "party_resolver.disambiguate.elicit_skipped",
            reason="client lacks elicitation capability",
        )
        return needs

    try:
        result = await ctx.elicit(
            message=f'Multiple {search_type} matched "{search}". Which one did you mean?',
            response_type=unique_labels,
        )
    except McpError as exc:
        if exc.error.code == METHOD_NOT_FOUND:
            logger.warning(
                "party_resolver.disambiguate.elicit_unsupported",
                error=str(exc),
            )
            return needs
        logger.warning("party_resolver.disambiguate.degraded", error=str(exc))
        return needs
    except Exception as exc:
        logger.warning("party_resolver.disambiguate.degraded", error=str(exc))
        return needs

    if isinstance(result, AcceptedElicitation):
        matching = label_to_candidate.get(result.data)
        if matching is None:
            return needs
        return Resolved(
            party=ResolvedParty(id=matching.id, type=search_type, name=matching.name),
        )

    assert isinstance(result, (DeclinedElicitation, CancelledElicitation))
    return needs
