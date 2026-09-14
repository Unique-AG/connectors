"""Classify a hard-delete elicit as CONFIRMED, NOT_AVAILABLE, or DECLINED."""

import pytest
from fastmcp.server.elicitation import AcceptedElicitation

from backstop_mcp.features.elicitation_utils import (
    DELETE,
    KEEP,
    DeletionChoice,
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
    async def test_requires_prompt_or_callback(self) -> None:
        async def prompt() -> str:
            return "Delete this note?"

        with pytest.raises(AssertionError, match="prompt or callback"):
            await elicit_entity_deletion(ctx_no_elicitation_capability())
        with pytest.raises(AssertionError, match="prompt or callback"):
            await elicit_entity_deletion(
                ctx_no_elicitation_capability(), "Delete this note?", callback=prompt
            )

    async def test_choosing_delete_returns_confirmed(self) -> None:
        assert (
            await elicit_entity_deletion(
                ctx_accept(DeletionChoice(choice=DELETE)), "Delete this note?"
            )
            is EntityDeletion.CONFIRMED
        )

    async def test_choosing_keep_returns_declined(self) -> None:
        assert (
            await elicit_entity_deletion(
                ctx_accept(DeletionChoice(choice=KEEP)), "Delete this note?"
            )
            is EntityDeletion.DECLINED
        )

    async def test_default_choice_is_keep(self) -> None:
        assert DeletionChoice().choice == KEEP

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

    async def test_missing_capability_does_not_run_the_callback(self) -> None:
        called = False

        async def prompt() -> str:
            nonlocal called
            called = True
            return "Delete this note?"

        assert (
            await elicit_entity_deletion(ctx_no_elicitation_capability(), callback=prompt)
            is EntityDeletion.NOT_AVAILABLE
        )
        assert called is False

    async def test_callback_builds_the_prompt_once_elicitation_is_available(self) -> None:
        captured: dict[str, object] = {}

        async def prompt() -> str:
            return "Permanently delete this note?"

        async def elicit(
            *, message: str, response_type: object
        ) -> AcceptedElicitation[DeletionChoice]:
            captured["message"] = message
            captured["response_type"] = response_type
            return AcceptedElicitation(data=DeletionChoice(choice=DELETE))

        outcome = await elicit_entity_deletion(as_context(FakeContext(elicit)), callback=prompt)

        assert outcome is EntityDeletion.CONFIRMED
        assert captured["message"] == "Permanently delete this note?"
        assert captured["response_type"] is DeletionChoice

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

    async def test_prompt_is_passed_through_as_a_choice_dropdown(self) -> None:
        captured: dict[str, object] = {}

        async def elicit(
            *, message: str, response_type: object
        ) -> AcceptedElicitation[DeletionChoice]:
            captured["message"] = message
            captured["response_type"] = response_type
            return AcceptedElicitation(data=DeletionChoice(choice=DELETE))

        outcome = await elicit_entity_deletion(
            as_context(FakeContext(elicit)), "Permanently delete this note?"
        )

        assert outcome is EntityDeletion.CONFIRMED
        assert captured["message"] == "Permanently delete this note?"
        assert captured["response_type"] is DeletionChoice
