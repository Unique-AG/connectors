"""Classify a hard-delete elicit as CONFIRMED, NOT_AVAILABLE, or DECLINED."""

from fastmcp.server.elicitation import AcceptedElicitation

from backstop_mcp.features.elicitation_utils import (
    DELETE_PERMANENTLY,
    KEEP_THIS_RECORD,
    EntityDeletion,
    elicit_entity_deletion,
)
from tests.features.party_resolver.helpers import (
    FakeContext,
    as_context,
    ctx_accept,
    ctx_cancel,
    ctx_decline,
    ctx_no_elicitation_capability,
    ctx_stalls,
    ctx_unsupported,
)


class TestElicitEntityDeletion:
    async def test_accept_returns_confirmed(self) -> None:
        assert (
            await elicit_entity_deletion(ctx_accept(DELETE_PERMANENTLY), "Delete this note?")
            is EntityDeletion.CONFIRMED
        )

    async def test_picking_keep_returns_declined(self) -> None:
        assert (
            await elicit_entity_deletion(ctx_accept(KEEP_THIS_RECORD), "Delete this note?")
            is EntityDeletion.DECLINED
        )

    async def test_dismissed_prompt_returns_declined(self) -> None:
        assert (
            await elicit_entity_deletion(ctx_decline(), "Delete this note?")
            is EntityDeletion.DECLINED
        )

    async def test_cancelled_prompt_returns_declined(self) -> None:
        assert (
            await elicit_entity_deletion(ctx_cancel(), "Delete this note?")
            is EntityDeletion.DECLINED
        )

    async def test_missing_capability_returns_not_available_without_eliciting(self) -> None:
        assert (
            await elicit_entity_deletion(ctx_no_elicitation_capability(), "Delete this note?")
            is EntityDeletion.NOT_AVAILABLE
        )

    async def test_timeout_returns_declined(self) -> None:
        assert (
            await elicit_entity_deletion(ctx_stalls(), "Delete this note?", timeout_seconds=0.05)
            is EntityDeletion.DECLINED
        )

    async def test_elicit_error_returns_declined(self) -> None:
        assert (
            await elicit_entity_deletion(ctx_unsupported(), "Delete this note?")
            is EntityDeletion.DECLINED
        )

    async def test_prompt_is_passed_through(self) -> None:
        prompts: list[str] = []

        async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
            _ = response_type
            prompts.append(message)
            return AcceptedElicitation(data=DELETE_PERMANENTLY)

        outcome = await elicit_entity_deletion(
            as_context(FakeContext(elicit)), "Permanently delete this note?"
        )

        assert outcome is EntityDeletion.CONFIRMED
        assert prompts == ["Permanently delete this note?"]
