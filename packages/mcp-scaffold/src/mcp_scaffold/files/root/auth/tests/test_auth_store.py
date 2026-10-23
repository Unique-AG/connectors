from typing import cast

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text

from mcp_skeleton.persistence import AuthStoreSettings
from mcp_skeleton.persistence import Persistence
from mcp_skeleton.persistence import SqlAuthStore
from mcp_skeleton.shared import PendingSignIn
from mcp_skeleton.shared import UpstreamCredentials


def credentials(username: str, password: str) -> UpstreamCredentials:
    return UpstreamCredentials(username=username, password=SecretStr(password))


def pending(request_id: str, *, expires_at: float) -> PendingSignIn:
    return PendingSignIn(
        request_id=request_id,
        client_id="client",
        scopes="",
        code_challenge="challenge",
        redirect_uri="http://localhost:6274/callback",
        redirect_uri_provided_explicitly=True,
        state=None,
        resource=None,
        expires_at=expires_at,
    )


async def test_a_password_is_kept_encrypted_and_read_back(persistence: Persistence) -> None:
    subject = await persistence.auth.save_credentials(credentials("ada", "s3cret"))

    credential = await persistence.auth.get_credentials(subject)
    async with persistence.database() as session:
        stored = cast(str, await session.scalar(text("SELECT password FROM mcp_auth_credentials")))

    assert credential is not None
    assert (credential.username, credential.password.get_secret_value()) == ("ada", "s3cret")
    assert "s3cret" not in stored


async def test_signing_in_again_keeps_the_subject_and_the_new_password(
    persistence: Persistence,
) -> None:
    first = await persistence.auth.save_credentials(credentials("ada", "old"))
    again = await persistence.auth.save_credentials(credentials("ada", "new"))

    credential = await persistence.auth.get_credentials(again)

    assert again == first
    assert credential is not None
    assert credential.password.get_secret_value() == "new"


async def test_a_new_encryption_key_makes_the_old_credentials_unreadable(
    persistence: Persistence,
) -> None:
    subject = await persistence.auth.save_credentials(credentials("ada", "s3cret"))
    rotated = SqlAuthStore(
        persistence.database,
        AuthStoreSettings(encryption_key=SecretStr(Fernet.generate_key().decode())),
    )

    assert await rotated.get_credentials(subject) is None


async def test_a_pending_sign_in_completes_once(persistence: Persistence) -> None:
    await persistence.auth.save_client(client_id="client", registration="{}", now=0)
    await persistence.auth.save_pending_sign_in(pending("request", expires_at=100))

    first = await persistence.auth.complete_sign_in(
        "request", code="code", subject="ada", code_expires_at=100, now=10
    )
    second = await persistence.auth.complete_sign_in(
        "request", code="other", subject="ada", code_expires_at=100, now=10
    )

    assert first is not None
    assert second is None
    assert await persistence.auth.take_authorization_code("code", client_id="client", now=10)
    assert not await persistence.auth.take_authorization_code("code", client_id="client", now=10)


async def test_purging_drops_what_expired_and_keeps_the_rest(persistence: Persistence) -> None:
    await persistence.auth.save_client(client_id="client", registration="{}", now=0)
    await persistence.auth.save_pending_sign_in(pending("stale", expires_at=5))
    await persistence.auth.save_pending_sign_in(pending("live", expires_at=100))
    await persistence.auth.record_failed_sign_in("ada", now=1)

    await persistence.auth.purge_expired(now=10, failed_sign_ins_before=5)

    assert await persistence.auth.get_pending_sign_in("stale", now=0) is None
    assert await persistence.auth.get_pending_sign_in("live", now=10) is not None
    assert await persistence.auth.count_failed_sign_ins("ada", since=0) == 0
