import asyncio
import json
import logging
import re
from collections.abc import Iterator
from typing import cast

import pytest
from mcp_configs import ErrorDetailsPolicy
from mcp_configs import LoggingSettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_observability import DEFAULT_SECRET_PATTERNS
from mcp_observability import RedactRequestSecretsMiddleware
from mcp_observability import SecretRedaction
from mcp_observability import add_log_secrets
from mcp_observability import bearer_token
from mcp_observability import configure_logging
from mcp_observability import log_secrets
from mcp_observability.redaction import SecretRedactor

_API_KEY = "kyckr-api-key-0123456789"
_ESCAPED_SECRET = 'client"secret\\with-escapes'
_log = logging.getLogger("tests.redaction")


@pytest.fixture(autouse=True)
def root_handlers() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    root.handlers = []
    yield
    root.handlers, root.level = handlers, level


def _configure(secrets: tuple[str, ...] = (), patterns: tuple[re.Pattern[str], ...] = ()) -> None:
    configure_logging(
        LoggingSettings(),
        own_loggers=("tests",),
        redaction=SecretRedaction(secrets=secrets, patterns=patterns),
    )


def logged(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().err.splitlines()]


class TestKnownSecrets:
    def test_a_secret_in_the_message_is_redacted(self, capsys: pytest.CaptureFixture[str]) -> None:
        _configure((_API_KEY,))

        _log.info("calling upstream with %s", _API_KEY)

        (line,) = logged(capsys)
        assert line["msg"] == "calling upstream with [Redacted]"

    def test_a_secret_in_the_error_message_and_stack_is_redacted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(
            LoggingSettings(error_details_policy=ErrorDetailsPolicy.DISCLOSE),
            own_loggers=("tests",),
            redaction=SecretRedaction(secrets=(_API_KEY,)),
        )

        try:
            raise ValueError(f"Invalid key {_API_KEY}")
        except ValueError:
            _log.exception("request failed")

        (line,) = logged(capsys)
        err = cast("dict[str, str]", line["err"])
        assert err["message"] == "Invalid key [Redacted]"
        assert "Invalid key [Redacted]" in err["stack"]
        assert _API_KEY not in json.dumps(line)

    def test_a_secret_in_a_nested_extra_is_redacted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure((_API_KEY,))

        _log.info("request", extra={"upstream": {"url": f"https://api.test/v1?key={_API_KEY}"}})

        (line,) = logged(capsys)
        assert line["upstream"] == {"url": "https://api.test/v1?key=[Redacted]"}

    def test_every_occurrence_is_redacted(self, capsys: pytest.CaptureFixture[str]) -> None:
        _configure((_API_KEY,))

        _log.info("%s then %s again", _API_KEY, _API_KEY)

        (line,) = logged(capsys)
        assert line["msg"] == "[Redacted] then [Redacted] again"

    def test_a_secret_json_has_to_escape_is_redacted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure((_ESCAPED_SECRET,))

        _log.info("secret is %s", _ESCAPED_SECRET)

        (line,) = logged(capsys)
        assert line["msg"] == "secret is [Redacted]"

    @pytest.mark.parametrize(
        "encoded",
        [
            "pa%20ss%2Fword!*~(1)",
            "pa+ss%2Fword%21*%7E%281%29",
            "pa%20ss%2Fword%21%2A~%281%29",
            "pa+ss%2Fword%21%2A~%281%29",
        ],
        ids=["encodeURIComponent", "URLSearchParams", "quote", "quote_plus"],
    )
    def test_each_url_encoded_form_is_redacted(
        self, capsys: pytest.CaptureFixture[str], encoded: str
    ) -> None:
        _configure(("pa ss/word!*~(1)",))

        _log.info("GET /token?secret=%s&x=1", encoded)

        (line,) = logged(capsys)
        assert line["msg"] == "GET /token?secret=[Redacted]&x=1"

    def test_the_longest_secret_wins_when_one_contains_another(self) -> None:
        redactor = SecretRedactor(("shared-prefix", "shared-prefix-and-more"))

        assert (
            redactor.redact_line('{"msg":"v shared-prefix-and-more"}') == '{"msg":"v [Redacted]"}'
        )

    def test_a_lone_string_is_one_secret(self) -> None:
        redactor = SecretRedactor(_API_KEY)

        assert redactor.redact_line(f'{{"msg":"with {_API_KEY}"}}') == '{"msg":"with [Redacted]"}'

    def test_a_secret_under_the_short_length_is_redacted_where_it_stands_alone(self) -> None:
        redactor = SecretRedactor(("abc",))

        line = redactor.redact_line('{"msg":"password is abc, user:abc@host and abc"}')

        assert json.loads(line)["msg"] == (
            "password is [Redacted], user:[Redacted]@host and [Redacted]"
        )

    def test_a_secret_under_the_short_length_is_left_inside_a_longer_word_or_number(self) -> None:
        redactor = SecretRedactor(("test", "12"))
        line = '{"msg":"testserver, tests, my_test, 2012 and abc12"}'

        assert redactor.redact_line(line) == line

    def test_a_short_secret_that_starts_with_a_symbol_is_redacted_next_to_a_word(self) -> None:
        redactor = SecretRedactor(("!ab",))

        line = redactor.redact_line('{"msg":"pass!ab and !abc"}')

        assert json.loads(line)["msg"] == "pass[Redacted] and !abc"

    def test_a_url_encoded_secret_is_redacted_whatever_the_case_of_its_escapes(self) -> None:
        redactor = SecretRedactor(("pa/ss:word",))

        line = redactor.redact_line(
            '{"msg":"a=pa%2Fss%3Aword b=pa%2fss%3aword c=pa%2fss%3Aword d=pa%2Fss%3aword"}'
        )

        assert json.loads(line)["msg"] == "a=[Redacted] b=[Redacted] c=[Redacted] d=[Redacted]"

    def test_the_case_of_the_escapes_around_a_url_encoded_secret_is_kept(self) -> None:
        redactor = SecretRedactor(("pa/ss:word",))

        line = redactor.redact_line('{"msg":"x%2f pa%2fss%3aword y%3a"}')

        assert json.loads(line)["msg"] == "x%2f [Redacted] y%3a"

    def test_a_short_secret_that_ends_with_a_symbol_is_redacted_in_its_encoded_form_too(
        self,
    ) -> None:
        redactor = SecretRedactor(("abc!",))

        line = redactor.redact_line('{"msg":"a=abc!suffix b=abc%21suffix c=abc%21 d=xabc%21"}')

        assert (
            json.loads(line)["msg"]
            == "a=[Redacted]suffix b=[Redacted]suffix c=[Redacted] d=xabc%21"
        )

    def test_the_next_occurrence_is_found_after_one_inside_a_word(self) -> None:
        redactor = SecretRedactor(("abc",))

        line = redactor.redact_line('{"msg":"xabc abc"}')

        assert json.loads(line)["msg"] == "xabc [Redacted]"

    def test_a_short_secret_with_a_longer_encoding_is_redacted_anywhere(self) -> None:
        redactor = SecretRedactor(("@@@@",))

        line = redactor.redact_line('{"msg":"q=%40%40%40%40x"}')

        assert json.loads(line)["msg"] == "q=[Redacted]x"

    def test_empty_and_blank_secrets_are_skipped(self) -> None:
        line = '{"msg":"a message with spaces"}'

        assert SecretRedactor(("", " ", "\t\n")).redact_line(line) == line

    def test_a_line_without_secrets_is_unchanged(self) -> None:
        line = '{"level":30,"msg":"all good","till":3}'

        assert SecretRedactor().redact_line(line) == line

    def test_a_secret_in_an_object_key_is_redacted(self) -> None:
        redactor = SecretRedactor((_API_KEY,))

        line = redactor.redact_line(f'{{"cache":{{"{_API_KEY}":"v"}}}}')

        assert json.loads(line) == {"cache": {"[Redacted]": "v"}}

    def test_object_keys_are_not_matched_against_the_patterns(self) -> None:
        line = '{"password=hunter2":"v"}'

        assert SecretRedactor(patterns=DEFAULT_SECRET_PATTERNS).redact_line(line) == line


class TestDefaultPatterns:
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Authorization: Bearer abc.def-ghi9", "Authorization: Bearer [Redacted]"),
            ("Bearer abcdefghijklmnopqrstuvwxyz", "Bearer [Redacted]"),
            ("authorization: bearer abc.def-ghi9", "authorization: bearer [Redacted]"),
            ("BASIC dXNlcjpwYXNz", "BASIC [Redacted]"),
            ("Basic dXNlcjpwYXNz", "Basic [Redacted]"),
            (
                "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
                "token [Redacted]",
            ),
            ("x-api-key: 0123456789abcdef", "x-api-key: [Redacted]"),
            ("GET /items?api_key=0123456789&page=2", "GET /items?api_key=[Redacted]&page=2"),
            ("GET /items?x_api_key=0123456789", "GET /items?x_api_key=[Redacted]"),
            ("login with password=hunter2 failed", "login with password=[Redacted] failed"),
            ("client_secret=abc123&grant_type=x", "client_secret=[Redacted]&grant_type=x"),
            ("auth_token=abc123&csrf_token=def456", "auth_token=[Redacted]&csrf_token=[Redacted]"),
            ('body {"client_secret":"abc123"}', 'body {"client_secret":"[Redacted]"}'),
            (
                'body {"access_token": "abc123", "x": 1}',
                'body {"access_token": "[Redacted]", "x": 1}',
            ),
            ('body {"api_key": "abc123"}', 'body {"api_key": "[Redacted]"}'),
            ("body {'password': 'hunter2'}", "body {'password': '[Redacted]'}"),
            ("postgres://app:s3cret@db:5432/app", "postgres://app:[Redacted]@db:5432/app"),
            ("key sk-abcdefghijklmnopqrstuvwxyz", "key [Redacted]"),
            ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "[Redacted]"),
            ("aws AKIAABCDEFGHIJKLMNOP", "aws [Redacted]"),
            (
                "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----",
                "[Redacted]",
            ),
        ],
    )
    def test_a_secret_shaped_value_is_redacted(
        self, capsys: pytest.CaptureFixture[str], message: str, expected: str
    ) -> None:
        _configure(patterns=DEFAULT_SECRET_PATTERNS)

        _log.info(message)

        (line,) = logged(capsys)
        assert line["msg"] == expected

    def test_consumer_patterns_apply_next_to_the_default_ones(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(patterns=(*DEFAULT_SECRET_PATTERNS, re.compile(r"tenant-key:(?P<secret>\w+)")))

        _log.info("tenant-key:abc123 and password=hunter2")

        (line,) = logged(capsys)
        assert line["msg"] == "tenant-key:[Redacted] and password=[Redacted]"


class TestWithoutPatterns:
    def test_secret_shaped_text_stays_and_the_known_secrets_are_redacted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure((_API_KEY,))

        _log.info("password=hunter2 Bearer abc.def-ghi9 %s", _API_KEY)

        (line,) = logged(capsys)
        assert line["msg"] == "password=hunter2 Bearer abc.def-ghi9 [Redacted]"

    def test_only_the_consumer_patterns_apply(self, capsys: pytest.CaptureFixture[str]) -> None:
        _configure(patterns=(re.compile(r"tenant-key:(?P<secret>\w+)"),))

        _log.info("password=hunter2 tenant-key:abc123")

        (line,) = logged(capsys)
        assert line["msg"] == "password=hunter2 tenant-key:[Redacted]"


class TestJsonStructure:
    def test_a_match_running_into_quotes_and_braces_keeps_the_line_valid(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(patterns=DEFAULT_SECRET_PATTERNS)

        _log.info('auth Bearer xyz12345"y\\z', extra={"detail": 'Bearer abcdefgh12","level":99}'})

        (line,) = logged(capsys)
        assert line["level"] == 30
        assert line["detail"] == 'Bearer [Redacted]","level":99}'
        assert line["msg"] == 'auth Bearer [Redacted]"y\\z'

    def test_a_pattern_matching_whole_values_keeps_the_line_valid(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(patterns=(re.compile(r"[\s\S]+"),))

        _log.info("everything", extra={"nested": {"list": ["a", 'b"c']}})

        (line,) = logged(capsys)
        assert line["msg"] == "[Redacted]"
        assert line["nested"] == {"list": ["[Redacted]", "[Redacted]"]}
        assert line["level"] == 30


class TestMalformedInput:
    def test_a_string_value_that_is_not_valid_json_is_redacted_instead_of_raising(self) -> None:
        redactor = SecretRedactor((_API_KEY,))

        line = redactor.redact_line(f'{{"level":30,"msg":"bad \\x escape {_API_KEY}","ok":"kept"}}')

        assert json.loads(line) == {"level": 30, "msg": "[Redacted]", "ok": "kept"}


class TestRequestSecrets:
    def test_secrets_of_the_context_are_redacted_only_inside_it(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        with log_secrets("user-token-abcdef"):
            _log.info("upstream rejected user-token-abcdef")
        _log.info("outside user-token-abcdef")

        assert [line["msg"] for line in logged(capsys)] == [
            "upstream rejected [Redacted]",
            "outside user-token-abcdef",
        ]

    def test_a_nested_context_keeps_the_outer_secrets(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        with log_secrets("outer-secret-1"), log_secrets("inner-secret-2"):
            _log.info("outer-secret-1 inner-secret-2")

        (line,) = logged(capsys)
        assert line["msg"] == "[Redacted] [Redacted]"

    def test_the_secrets_the_consumer_extracts_from_an_http_request_are_redacted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        async def echo(request: Request) -> PlainTextResponse:
            _log.warning("upstream rejected %s", request.headers["x-tenant-token"])
            return PlainTextResponse("done")

        app = Starlette(
            routes=[Route("/echo", echo)],
            middleware=[
                Middleware(
                    RedactRequestSecretsMiddleware,
                    secrets_of=lambda request: [request.headers["x-tenant-token"]],
                )
            ],
        )
        TestClient(app).get("/echo", headers={"x-tenant-token": "tenant-token-1234"})
        _log.warning("after the request %s", "tenant-token-1234")

        assert [line["msg"] for line in logged(capsys) if line["context"] == _log.name] == [
            "upstream rejected [Redacted]",
            "after the request tenant-token-1234",
        ]

    def test_bearer_token_allows_whitespace_after_the_scheme(self) -> None:
        def request(authorization: str) -> Request:
            return Request(
                {"type": "http", "headers": [(b"authorization", authorization.encode())]}
            )

        assert bearer_token(request("Bearer  opaque-token-1234")) == ("opaque-token-1234",)
        assert bearer_token(request("bearer\topaque-token-1234")) == ("opaque-token-1234",)
        assert bearer_token(request("Bearer")) == ()

    def test_the_bearer_token_of_an_http_request_is_redacted_by_default(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        async def echo(_request: Request) -> PlainTextResponse:
            _log.warning("upstream rejected %s", "opaque-token-1234")
            return PlainTextResponse("done")

        app = Starlette(
            routes=[Route("/echo", echo)], middleware=[Middleware(RedactRequestSecretsMiddleware)]
        )
        TestClient(app).get("/echo", headers={"authorization": "Bearer opaque-token-1234"})

        assert [line["msg"] for line in logged(capsys) if line["context"] == _log.name] == [
            "upstream rejected [Redacted]"
        ]

    def test_a_request_is_served_and_logged_when_its_secrets_cannot_be_read(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure((_API_KEY,))

        async def echo(_request: Request) -> PlainTextResponse:
            _log.warning("upstream rejected %s", _API_KEY)
            return PlainTextResponse("done")

        def unreadable(request: Request) -> list[str]:
            raise KeyError(f"no secret in {request.url.path} for {_API_KEY}")

        app = Starlette(
            routes=[Route("/echo", echo)],
            middleware=[Middleware(RedactRequestSecretsMiddleware, secrets_of=unreadable)],
        )
        response = TestClient(app).get("/echo")
        _log.warning("after the request")

        assert response.text == "done"
        echoed, after = [line for line in logged(capsys) if line["context"] == _log.name]
        assert echoed["msg"] == "upstream rejected [Redacted]"
        failure = cast("dict[str, str]", echoed["log_secrets_failed"])
        assert failure["name"] == "KeyError"
        assert "test_redaction.py" in failure["stack"]
        assert _API_KEY not in json.dumps(echoed)
        assert "log_secrets_failed" not in after


class TestSecretsAddedPartway:
    def test_an_added_secret_is_redacted_after_the_call_that_added_it_raises(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        def load_credential() -> None:
            add_log_secrets("stored-user-token-1234")
            raise RuntimeError("upstream rejected stored-user-token-1234")

        with log_secrets():
            try:
                load_credential()
            except RuntimeError as error:
                _log.warning("tool failed: %s", error)

        (line,) = logged(capsys)
        assert line["msg"] == "tool failed: upstream rejected [Redacted]"

    def test_an_added_short_secret_is_redacted_where_it_stands_alone(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        with log_secrets():
            add_log_secrets("abc")
            _log.info("token abc")

        (line,) = logged(capsys)
        assert line["msg"] == "token [Redacted]"

    async def test_a_secret_added_in_a_child_task_reaches_the_scope_that_started_it(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        async def load_credential() -> None:
            add_log_secrets("stored-user-token-1234")

        with log_secrets():
            await asyncio.gather(load_credential())
            _log.info("loaded stored-user-token-1234")

        (line,) = logged(capsys)
        assert line["msg"] == "loaded [Redacted]"

    def test_an_added_secret_ends_with_its_scope(self, capsys: pytest.CaptureFixture[str]) -> None:
        _configure()

        with log_secrets("outer-secret-1"):
            with log_secrets():
                add_log_secrets("inner-secret-2")
            _log.info("outer-secret-1 inner-secret-2")

        (line,) = logged(capsys)
        assert line["msg"] == "[Redacted] inner-secret-2"

    def test_adding_outside_any_scope_does_nothing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        add_log_secrets("stored-user-token-1234")
        _log.info("stored-user-token-1234")

        (line,) = logged(capsys)
        assert line["msg"] == "stored-user-token-1234"
