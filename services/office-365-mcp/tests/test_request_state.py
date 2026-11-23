import pytest
from mcp.server.request_state import (
    AESGCMRequestStateCodec,
    InvalidRequestState,
    RequestStateCodec,
)

from office_365_mcp.server.request_state import SingleUseRequestState, request_state_security

_KEY = b"k" * 32
_PAYLOAD = b'{"s":"approval"}'


class _Clock:
    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now


def _single_use(clock: _Clock) -> SingleUseRequestState:
    return SingleUseRequestState(AESGCMRequestStateCodec([_KEY]), remembered_for=660.0, clock=clock)


def _answer(codec: RequestStateCodec, token: str) -> bytes:
    assert isinstance(codec, SingleUseRequestState)
    payload = codec.unseal(token)
    codec.spend(token)
    return payload


class TestSingleUseRequestState:
    def test_a_sealed_answer_unseals_once(self) -> None:
        codec = _single_use(_Clock())
        token = codec.seal(_PAYLOAD)

        assert _answer(codec, token) == _PAYLOAD
        with pytest.raises(InvalidRequestState, match="replayed"):
            _ = codec.unseal(token)

    def test_an_unsealed_token_is_not_spent_until_its_call_is_accepted(self) -> None:
        codec = _single_use(_Clock())
        token = codec.seal(_PAYLOAD)

        assert codec.unseal(token) == _PAYLOAD
        assert _answer(codec, token) == _PAYLOAD
        with pytest.raises(InvalidRequestState, match="replayed"):
            codec.spend(token)

    def test_each_question_seals_its_own_answer(self) -> None:
        codec = _single_use(_Clock())
        first, second = codec.seal(_PAYLOAD), codec.seal(_PAYLOAD)

        assert codec.unseal(first) == _PAYLOAD
        assert codec.unseal(second) == _PAYLOAD

    def test_a_token_it_cannot_unseal_is_not_remembered(self) -> None:
        codec = _single_use(_Clock())

        for _ in range(2):
            with pytest.raises(InvalidRequestState, match="malformed"):
                _ = codec.unseal("v1.not-a-token")

    def test_a_spent_token_is_forgotten_only_after_it_has_expired(self) -> None:
        clock = _Clock()
        codec = _single_use(clock)
        token = codec.seal(_PAYLOAD)
        _ = _answer(codec, token)

        clock.now += 659.0
        with pytest.raises(InvalidRequestState, match="replayed"):
            _ = codec.unseal(token)
        clock.now += 1.0
        assert codec.unseal(token) == _PAYLOAD

    def test_forgetting_an_expired_token_keeps_a_later_one_spent(self) -> None:
        clock = _Clock()
        codec = _single_use(clock)
        earlier, later = codec.seal(_PAYLOAD), codec.seal(_PAYLOAD)
        _ = _answer(codec, earlier)
        clock.now += 100.0
        _ = _answer(codec, later)

        clock.now += 600.0
        assert codec.unseal(earlier) == _PAYLOAD
        with pytest.raises(InvalidRequestState, match="replayed"):
            _ = codec.unseal(later)


def test_the_server_policy_seals_single_use_answers() -> None:
    security = request_state_security()
    token = security.codec.seal(_PAYLOAD)

    assert _answer(security.codec, token) == _PAYLOAD
    with pytest.raises(InvalidRequestState, match="replayed"):
        _ = security.codec.unseal(token)
    assert security.ttl == 600.0
