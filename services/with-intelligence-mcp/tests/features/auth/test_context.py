"""Resolving whose credential to use, and what happens when there isn't one."""

import uuid
from collections.abc import Callable

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from tests.conftest import DatabaseFixture
from with_intelligence_mcp.db import transaction
from with_intelligence_mcp.features.auth import NotConnectedError, WithIntelligenceAuthContext
from with_intelligence_mcp.features.auth.credential_store import save_credential
from with_intelligence_mcp.with_intelligence_client import VendorCredential

KEY = Fernet.generate_key()


async def _noop(_subject: str) -> None:
    return None


def _fixed_subject(subject: str) -> Callable[[WithIntelligenceAuthContext], str]:
    """Stands in for the access token FastMCP would have validated for a real request."""

    def current_subject(_self: WithIntelligenceAuthContext) -> str:
        return subject

    return current_subject


def _context(db: DatabaseFixture) -> WithIntelligenceAuthContext:
    _, factory = db
    return WithIntelligenceAuthContext(
        session_factory=factory, encryption_key=KEY, revoke_tokens_for_subject=_noop
    )


class TestOutsideARequest:
    async def test_an_unauthenticated_caller_is_told_to_connect(self, db: DatabaseFixture) -> None:
        """No access token is active outside a request, which is the same shape as not logged in."""
        with pytest.raises(NotConnectedError, match="complete the login flow"):
            _ = await _context(db).current_credential()

    def test_the_subject_is_none_outside_a_request(self, db: DatabaseFixture) -> None:
        assert _context(db).current_subject() is None


class TestStoredCredential:
    async def test_a_known_subject_with_no_row_is_told_to_reconnect(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        context = _context(db)
        absent = str(uuid.uuid4())
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(absent), raising=True)
        with pytest.raises(NotConnectedError, match="please reconnect"):
            _ = await context.current_credential()

    async def test_a_stored_credential_is_returned_for_its_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        username = f"context-{uuid.uuid4().hex[:8]}@example.invalid"
        async with transaction(factory) as session:
            user_id = await save_credential(
                session,
                str(uuid.uuid4()),
                VendorCredential(username=username, password=SecretStr("ctx-pw")),
                KEY,
            )
        context = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(user_id), raising=True)
        credential = await context.current_credential()
        assert credential.username == username
        assert credential.password.get_secret_value() == "ctx-pw"
