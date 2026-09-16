"""Classify a hard-delete elicit as a tool return, or `None` to proceed."""

import pytest
from fastmcp.exceptions import ToolError
from mcp.types import ElicitRequestFormParams, ElicitResult, InputRequiredResult

from backstop_mcp.features.elicitation_utils import (
    CONFIRM_RETRY_MESSAGE,
    DELETE,
    DELETION_INPUT_KEY,
    DELETION_NOT_CONFIRMED,
    KEEP,
    DeletionChoice,
    DeletionNeedsConfirmationResponse,
    elicit_entity_deletion,
)
from tests.features.party_resolver.helpers import (
    ctx_deletion_answer,
    ctx_handshake_era,
    ctx_never_elicit,
    ctx_no_elicitation_capability,
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

    async def test_default_choice_is_keep(self) -> None:
        assert DeletionChoice().choice == KEEP

    async def test_missing_capability_returns_none_without_asking(self) -> None:
        assert (
            await elicit_entity_deletion(ctx_no_elicitation_capability(), "Delete this note?")
            is None
        )

    async def test_missing_capability_does_not_run_the_callback(self) -> None:
        called = False

        async def prompt() -> str:
            nonlocal called
            called = True
            return "Delete this note?"

        assert (
            await elicit_entity_deletion(ctx_no_elicitation_capability(), callback=prompt) is None
        )
        assert called is False

    async def test_handshake_era_returns_needs_confirmation(self) -> None:
        outcome = await elicit_entity_deletion(ctx_handshake_era(), "Delete this note?")

        assert isinstance(outcome, DeletionNeedsConfirmationResponse)
        assert outcome.status == "needs_confirmation"
        assert outcome.preview == "Delete this note?"
        assert outcome.message == CONFIRM_RETRY_MESSAGE

    async def test_handshake_era_runs_the_callback(self) -> None:
        called = False

        async def prompt() -> str:
            nonlocal called
            called = True
            return "Permanently delete this note?"

        outcome = await elicit_entity_deletion(ctx_handshake_era(), callback=prompt)

        assert called is True
        assert isinstance(outcome, DeletionNeedsConfirmationResponse)
        assert outcome.preview == "Permanently delete this note?"

    async def test_capable_client_returns_input_required(self) -> None:
        outcome = await elicit_entity_deletion(ctx_never_elicit(), "Delete this note?")

        assert isinstance(outcome, InputRequiredResult)
        assert outcome.input_requests is not None
        params = outcome.input_requests[DELETION_INPUT_KEY].params
        assert isinstance(params, ElicitRequestFormParams)
        assert params.message == "Delete this note?"

    async def test_callback_builds_the_prompt_once_elicitation_is_available(self) -> None:
        called = False

        async def prompt() -> str:
            nonlocal called
            called = True
            return "Permanently delete this note?"

        outcome = await elicit_entity_deletion(ctx_never_elicit(), callback=prompt)

        assert called is True
        assert isinstance(outcome, InputRequiredResult)
        assert outcome.input_requests is not None
        params = outcome.input_requests[DELETION_INPUT_KEY].params
        assert isinstance(params, ElicitRequestFormParams)
        assert params.message == "Permanently delete this note?"

    async def test_retry_accepting_delete_returns_none(self) -> None:
        assert (
            await elicit_entity_deletion(
                ctx_deletion_answer(ElicitResult(action="accept", content={"choice": DELETE})),
                "Delete this note?",
            )
            is None
        )

    async def test_retry_keeping_the_record_raises(self) -> None:
        with pytest.raises(ToolError, match="not confirmed") as raised:
            await elicit_entity_deletion(
                ctx_deletion_answer(ElicitResult(action="accept", content={"choice": KEEP})),
                "Delete this note?",
            )
        assert DELETION_NOT_CONFIRMED in str(raised.value)

    async def test_retry_declining_raises(self) -> None:
        with pytest.raises(ToolError, match="not confirmed"):
            await elicit_entity_deletion(
                ctx_deletion_answer(ElicitResult(action="decline")),
                "Delete this note?",
            )

    async def test_retry_cancelling_raises(self) -> None:
        with pytest.raises(ToolError, match="not confirmed"):
            await elicit_entity_deletion(
                ctx_deletion_answer(ElicitResult(action="cancel")),
                "Delete this note?",
            )

    async def test_retry_does_not_run_the_callback(self) -> None:
        called = False

        async def prompt() -> str:
            nonlocal called
            called = True
            return "Delete this note?"

        assert (
            await elicit_entity_deletion(
                ctx_deletion_answer(ElicitResult(action="accept", content={"choice": DELETE})),
                callback=prompt,
            )
            is None
        )
        assert called is False
