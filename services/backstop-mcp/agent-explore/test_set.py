#!/usr/bin/env python3
"""Run a 1Password question set against a local Cursor agent that can only use MCP.

The question set is a JSON document (or markdown tables) stored in 1Password so
other repos can share it. `OP_TEST_SET` is an `op://` reference; this script
calls `op read` and never keeps the body in the repo.

Usage, from services/backstop-mcp:

    uv run python agent-explore/test_set.py --list
    uv run python agent-explore/test_set.py --ids A1,A5
    uv run python agent-explore/test_set.py --all

JSON shape in the 1Password item (notes or file):

    {"cases": [{"id": "A1", "group": "optional", "question": "...", "expected": "..."}]}

Both the Cursor agent and backstop-mcp run on this machine. Start the server
with `uv run backstop-mcp` (http://localhost:9010/mcp), then this script.
Requires `op` signed in, `CURSOR_API_KEY`, and `BACKSTOP_SERVICE_USERNAME` /
`BACKSTOP_SERVICE_API_TOKEN`. The script completes the local MCP OAuth form
itself; no Cursor-app login is needed.

`cursor-sdk` is not a locked service dependency. Install it locally before a
run: `uv pip install cursor-sdk==1.0.31`.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from urllib.parse import parse_qs, urlparse

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError
from test_set_classify import (
    DEFAULT_MCP_NAME,
    JudgeScore,
    ToolCall,
    Verdict,
    _as_string_map,
    _split_tools,
    _tool_call_name,
    _verdict,
)

HERE = Path(__file__).resolve().parent
DEFAULT_MCP_URL = "http://localhost:9010/mcp"
DEFAULT_MODEL = "grok-4.6"
RUNS_DIR = HERE / ".test-set-runs"
_OAUTH_REDIRECT = "http://127.0.0.1:9/callback"
_OAUTH_REFRESH_SKEW = timedelta(minutes=2)
_HIDDEN_INPUT = re.compile(r'name="([a-z_]+)" value="([^"]*)"')

_USE_CASE = re.compile(r"^## Use case ([A-Z])\b")
_TABLE_ROW = re.compile(r"^\| (.+) \| (.+) \|$")
_JSON_OBJECT: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])
_JSON_VALUE: TypeAdapter[object] = TypeAdapter(object)
_CURSOR_SDK_SPEC = "cursor-sdk==1.0.31"


@cache
def _cursor_sdk() -> SimpleNamespace:
    try:
        from cursor_sdk import (
            Agent,
            AgentOptions,
            CursorAgentError,
            HttpMcpServerConfig,
            LocalAgentOptions,
            ModelParameterValue,
            ModelSelection,
        )
    except ImportError as exc:
        raise SystemExit(
            "cursor-sdk is not a locked service dependency. Install it locally "
            + f"with `uv pip install {_CURSOR_SDK_SPEC}` to run the harness."
        ) from exc
    return SimpleNamespace(
        Agent=Agent,
        AgentOptions=AgentOptions,
        CursorAgentError=CursorAgentError,
        HttpMcpServerConfig=HttpMcpServerConfig,
        LocalAgentOptions=LocalAgentOptions,
        ModelParameterValue=ModelParameterValue,
        ModelSelection=ModelSelection,
    )


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    question: str
    expected: str


@dataclass
class CaseResult:
    case_id: str
    question: str
    answer: str
    expected: str
    tool_calls: list[ToolCall]
    mcp_tools: list[str]
    other_tools: list[str]
    run_status: str
    agent_id: str
    run_id: str
    judge: JudgeScore | None
    verdict: Verdict
    error: str | None = None


@dataclass
class McpAuthState:
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    token_endpoint: str
    resource: str
    expires_at: datetime


@dataclass(frozen=True)
class Harness:
    api_key: str
    mcp_url: str
    model: str
    judge_model: str
    judge: bool
    quiet: bool
    mcp_auth: McpAuthState


class _Args(argparse.Namespace):
    ids: str
    run_all: bool
    model: str
    judge_model: str
    mcp_url: str
    list_only: bool
    no_judge: bool
    strict: bool
    skip_existing: bool
    quiet: bool

    def __init__(self) -> None:
        super().__init__()
        self.ids = ""
        self.run_all = False
        self.model = DEFAULT_MODEL
        self.judge_model = DEFAULT_MODEL
        self.mcp_url = ""
        self.list_only = False
        self.no_judge = False
        self.strict = False
        self.skip_existing = False
        self.quiet = False


def main() -> None:
    load_dotenv(HERE / ".env")
    args = _parse_args()
    cases = _select_cases(_load_test_set(), ids=args.ids, run_all=args.run_all or args.list_only)
    if args.list_only:
        for case in cases:
            print(f"{case.case_id}\t{case.question}")
        return

    mcp_url = _mcp_url_from_env(args)
    _require_mcp(mcp_url)
    if not args.quiet:
        print("logging in to local MCP...", flush=True)
    harness = _harness_from_env(args, mcp_url=mcp_url, mcp_auth=_mcp_login(mcp_url))

    RUNS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results: list[CaseResult] = []
    for case in cases:
        out_file = RUNS_DIR / f"{case.case_id}.json"
        if args.skip_existing and out_file.exists():
            loaded = _load_result(out_file)
            if loaded is not None:
                results.append(loaded)
                _print_row(loaded, quiet=args.quiet)
                continue
        _refresh_mcp_auth(harness.mcp_auth)
        result = _run_case(case, harness=harness)
        out_file.write_text(_dump_result(result))
        (RUNS_DIR / f"{stamp}-{case.case_id}.json").write_text(_dump_result(result))
        results.append(result)
        _print_row(result, quiet=args.quiet)

    failed = [row for row in results if _is_failure(row, strict=args.strict)]
    print(
        f"{len(results)} cases  "
        + f"{_count(results, 'pass')} pass  "
        + f"{_count(results, 'partial')} partial  "
        + f"{_count(results, 'fail')} fail  "
        + f"{_count(results, 'error')} error"
    )
    if failed:
        raise SystemExit(1)


def _parse_args() -> _Args:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default="", help="Comma-separated ids, e.g. A1,B3")
    parser.add_argument("--all", dest="run_all", action="store_true", help="Run every case")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--judge-model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--mcp-url",
        default="",
        help="Local MCP URL. Defaults to BACKSTOP_MCP_URL or http://localhost:9010/mcp.",
    )
    parser.add_argument("--list", dest="list_only", action="store_true")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Treat partial as failure")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Reuse agent-explore/.test-set-runs/<id>.json when present",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(namespace=_Args())


def _load_test_set() -> tuple[Case, ...]:
    ref = os.environ.get("OP_TEST_SET", "").strip()
    if not ref:
        raise SystemExit(
            "OP_TEST_SET is missing. Set it in agent-explore/.env to an op:// "
            + "reference (see .env.example)."
        )
    return _parse_test_set(_op_read(ref))


def _op_read(ref: str) -> str:
    if not ref.startswith("op://"):
        raise SystemExit("OP_TEST_SET must be an op:// vault/item/field reference")
    command = ["op", "read", ref]
    account = os.environ.get("OP_ACCOUNT", "").strip()
    if account:
        command.extend(["--account", account])
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit(
            "1Password CLI (`op`) is not on PATH. Install it and run `op signin`."
        ) from None
    if completed.returncode != 0:
        err = completed.stderr.strip() or "op read failed"
        raise SystemExit(f"could not read OP_TEST_SET: {err}")
    body = completed.stdout.strip()
    if not body:
        raise SystemExit("OP_TEST_SET resolved to an empty item")
    return body


def _parse_test_set(raw: str) -> tuple[Case, ...]:
    stripped = raw.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        cases = _parse_json_cases(stripped)
    else:
        cases = _parse_markdown_cases(stripped)
    if not cases:
        raise SystemExit("OP_TEST_SET contained no cases")
    return cases


def _parse_json_cases(raw: str) -> tuple[Case, ...]:
    try:
        payload = _JSON_VALUE.validate_json(raw)
    except ValidationError as exc:
        raise SystemExit("OP_TEST_SET JSON did not parse") from exc
    rows = _json_case_rows(payload)
    if rows is None:
        raise SystemExit('OP_TEST_SET JSON must be an array or {"cases": [...]}')
    cases: list[Case] = []
    items = rows
    for index, item in enumerate(items, start=1):
        parsed = _as_string_map(item)
        if parsed is None:
            raise SystemExit(f"case {index} is not an object")
        case_id = parsed.get("id")
        question = parsed.get("question")
        expected = parsed.get("expected")
        group = parsed.get("group")
        if not isinstance(case_id, str) or not case_id.strip():
            raise SystemExit(f"case {index} is missing id")
        if not isinstance(question, str) or not question.strip():
            raise SystemExit(f"case {case_id} is missing question")
        if not isinstance(expected, str):
            raise SystemExit(f"case {case_id} is missing expected")
        cases.append(
            Case(
                case_id=case_id.strip(),
                group=group.strip() if isinstance(group, str) else "",
                question=question.strip(),
                expected=expected,
            )
        )
    return tuple(cases)


def _json_case_rows(payload: object) -> list[object] | None:
    if isinstance(payload, list):
        return cast(list[object], payload)
    mapped = _as_string_map(payload)
    if mapped is None:
        return None
    rows = mapped.get("cases")
    if not isinstance(rows, list):
        return None
    return cast(list[object], rows)


def _parse_markdown_cases(raw: str) -> tuple[Case, ...]:
    cases: list[Case] = []
    group = ""
    letter = ""
    index = 0
    for line in raw.splitlines():
        heading = _USE_CASE.match(line)
        if heading is not None:
            letter = heading.group(1)
            group = line.removeprefix("## ").strip()
            index = 0
            continue
        row = _TABLE_ROW.match(line)
        if row is None or letter == "":
            continue
        question = row.group(1).strip()
        expected = row.group(2).strip()
        if question.lower() == "question" or set(question) <= {"-"}:
            continue
        index += 1
        cases.append(
            Case(
                case_id=f"{letter}{index}",
                group=group,
                question=question,
                expected=expected,
            )
        )
    return tuple(cases)


def _select_cases(cases: Sequence[Case], *, ids: str, run_all: bool) -> tuple[Case, ...]:
    if ids.strip() and run_all:
        raise SystemExit("pass --ids or --all, not both")
    if ids.strip():
        wanted = [item.strip() for item in ids.split(",") if item.strip()]
        by_id = {case.case_id: case for case in cases}
        by_upper = {case.case_id.upper(): case for case in cases}
        unknown = [
            case_id
            for case_id in wanted
            if case_id not in by_id and case_id.upper() not in by_upper
        ]
        if unknown:
            raise SystemExit(f"unknown case ids: {', '.join(unknown)}")
        return tuple(by_id.get(case_id) or by_upper[case_id.upper()] for case_id in wanted)
    if run_all:
        return tuple(cases)
    raise SystemExit("pass --ids A1,A5 or --all (or --list)")


def _mcp_url_from_env(args: _Args) -> str:
    mcp_url = (args.mcp_url or os.environ.get("BACKSTOP_MCP_URL") or DEFAULT_MCP_URL).strip()
    if not _is_loopback(mcp_url):
        raise SystemExit(
            "test_set.py talks to a local MCP only "
            + f"(got {mcp_url!r}; expected 127.0.0.1 or localhost)."
        )
    return mcp_url


def _harness_from_env(args: _Args, *, mcp_url: str, mcp_auth: McpAuthState) -> Harness:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "CURSOR_API_KEY is missing. Put it in agent-explore/.env "
            + "(see .env.example) or export it."
        )
    return Harness(
        api_key=api_key,
        mcp_url=mcp_url,
        model=args.model,
        judge_model=args.judge_model,
        judge=not args.no_judge,
        quiet=args.quiet,
        mcp_auth=mcp_auth,
    )


def _is_loopback(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in {"127.0.0.1", "localhost", "::1"}


def _mcp_origin(mcp_url: str) -> str:
    parsed = urlparse(mcp_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _backstop_login_creds() -> tuple[str, str]:
    username = os.environ.get("BACKSTOP_SERVICE_USERNAME", "").strip()
    token = os.environ.get("BACKSTOP_SERVICE_API_TOKEN", "").strip()
    if not username or not token:
        raise SystemExit(
            "BACKSTOP_SERVICE_USERNAME and BACKSTOP_SERVICE_API_TOKEN are required "
            + "so test_set.py can log in to the local MCP (see .env.example)."
        )
    return username, token


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _hidden_inputs(html: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in _HIDDEN_INPUT.finditer(html)}


def _mcp_login(mcp_url: str) -> McpAuthState:
    username, api_token = _backstop_login_creds()
    origin = _mcp_origin(mcp_url)
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            metadata = _oauth_metadata(client, origin)
            registration = _register_oauth_client(client, metadata["registration_endpoint"])
            login_url = _authorize_login_url(
                client,
                metadata["authorization_endpoint"],
                client_id=registration["client_id"],
                challenge=challenge,
                state=state,
                resource=mcp_url,
            )
            form = client.get(login_url)
            if form.status_code >= 400:
                raise SystemExit(f"MCP login form returned HTTP {form.status_code}")
            fields = _hidden_inputs(form.text)
            request_id = fields.get("request_id", "")
            csrf_token = fields.get("csrf_token", "")
            if not request_id or not csrf_token:
                raise SystemExit("MCP login form is missing request_id or csrf_token")
            submitted = client.post(
                login_url.split("?", 1)[0],
                data={
                    "request_id": request_id,
                    "csrf_token": csrf_token,
                    "username": username,
                    "api_token": api_token,
                },
            )
            if submitted.status_code != 302:
                raise SystemExit(_login_failure_message(submitted))
            redirect = _header(submitted, "location")
            code = _authorization_code(redirect, expected_state=state)
            tokens = _exchange_code(
                client,
                metadata["token_endpoint"],
                client_id=registration["client_id"],
                client_secret=registration["client_secret"],
                code=code,
                verifier=verifier,
                resource=mcp_url,
            )
    except httpx.HTTPError as exc:
        raise SystemExit(f"MCP OAuth failed: {exc}") from exc
    return _auth_state(
        tokens,
        client_id=registration["client_id"],
        client_secret=registration["client_secret"],
        token_endpoint=metadata["token_endpoint"],
        resource=mcp_url,
    )


def _oauth_metadata(client: httpx.Client, origin: str) -> dict[str, str]:
    response = client.get(f"{origin}/.well-known/oauth-authorization-server")
    if response.status_code >= 400:
        raise SystemExit(f"OAuth discovery returned HTTP {response.status_code}")
    payload = _as_string_map(_json_body(response))
    if payload is None:
        raise SystemExit("OAuth discovery returned a non-object")
    required = (
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
    )
    missing = [key for key in required if not isinstance(payload.get(key), str)]
    if missing:
        raise SystemExit(f"OAuth discovery is missing {', '.join(missing)}")
    return {key: str(payload[key]) for key in required}


def _register_oauth_client(client: httpx.Client, endpoint: str) -> dict[str, str]:
    response = client.post(
        endpoint,
        json={
            "client_name": "test_set.py",
            "redirect_uris": [_OAUTH_REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    if response.status_code >= 400:
        raise SystemExit(f"OAuth client registration returned HTTP {response.status_code}")
    payload = _as_string_map(_json_body(response))
    if payload is None:
        raise SystemExit("OAuth client registration returned a non-object")
    client_id = payload.get("client_id")
    client_secret = payload.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        raise SystemExit("OAuth client registration omitted client_id or client_secret")
    return {"client_id": client_id, "client_secret": client_secret}


def _authorize_login_url(
    client: httpx.Client,
    endpoint: str,
    *,
    client_id: str,
    challenge: str,
    state: str,
    resource: str,
) -> str:
    response = client.get(
        endpoint,
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": _OAUTH_REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "resource": resource,
        },
    )
    if response.status_code != 302:
        raise SystemExit(f"OAuth authorize returned HTTP {response.status_code}")
    location = _header(response, "location")
    if "/backstop/login" not in location or "request_id=" not in location:
        raise SystemExit("OAuth authorize did not redirect to the Backstop login form")
    if location.startswith("http://") or location.startswith("https://"):
        return location
    parsed = urlparse(endpoint)
    return f"{parsed.scheme}://{parsed.netloc}{location}"


def _login_failure_message(response: httpx.Response) -> str:
    if "Invalid username or API token" in response.text:
        return "MCP login rejected BACKSTOP_SERVICE_USERNAME / BACKSTOP_SERVICE_API_TOKEN"
    if "Too many failed attempts" in response.text:
        return "MCP login is throttled for this username; wait and retry"
    if "expired" in response.text.casefold():
        return "MCP login form expired before it was submitted"
    return f"MCP login returned HTTP {response.status_code}"


def _authorization_code(redirect: str, *, expected_state: str) -> str:
    parsed = urlparse(redirect)
    query = parse_qs(parsed.query)
    state = (query.get("state") or [""])[0]
    code = (query.get("code") or [""])[0]
    if state != expected_state:
        raise SystemExit("MCP login redirect state did not match")
    if not code:
        raise SystemExit("MCP login redirect did not include an authorization code")
    return code


def _exchange_code(
    client: httpx.Client,
    endpoint: str,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    verifier: str,
    resource: str,
) -> dict[str, object]:
    response = client.post(
        endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _OAUTH_REDIRECT,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
            "resource": resource,
        },
    )
    if response.status_code >= 400:
        raise SystemExit(f"OAuth token exchange returned HTTP {response.status_code}")
    payload = _as_string_map(_json_body(response))
    if payload is None:
        raise SystemExit("OAuth token exchange returned a non-object")
    return payload


def _auth_state(
    tokens: dict[str, object],
    *,
    client_id: str,
    client_secret: str,
    token_endpoint: str,
    resource: str,
) -> McpAuthState:
    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not isinstance(access, str) or not access:
        raise SystemExit("OAuth token response omitted access_token")
    expires_in = tokens.get("expires_in")
    if isinstance(expires_in, int):
        lifetime = expires_in
    elif isinstance(expires_in, float):
        lifetime = int(expires_in)
    else:
        lifetime = 900
    return McpAuthState(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) else "",
        client_id=client_id,
        client_secret=client_secret,
        token_endpoint=token_endpoint,
        resource=resource,
        expires_at=datetime.now(UTC) + timedelta(seconds=lifetime),
    )


def _refresh_mcp_auth(auth: McpAuthState) -> None:
    if datetime.now(UTC) + _OAUTH_REFRESH_SKEW < auth.expires_at:
        return
    if not auth.refresh_token:
        raise SystemExit("MCP access token expired and no refresh token is available")
    try:
        response = httpx.post(
            auth.token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": auth.refresh_token,
                "client_id": auth.client_id,
                "client_secret": auth.client_secret,
                "resource": auth.resource,
            },
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise SystemExit(f"OAuth refresh failed: {exc}") from exc
    if response.status_code >= 400:
        raise SystemExit(f"OAuth refresh returned HTTP {response.status_code}")
    payload = _as_string_map(_json_body(response))
    if payload is None:
        raise SystemExit("OAuth refresh returned a non-object")
    refreshed = _auth_state(
        payload,
        client_id=auth.client_id,
        client_secret=auth.client_secret,
        token_endpoint=auth.token_endpoint,
        resource=auth.resource,
    )
    auth.access_token = refreshed.access_token
    auth.refresh_token = refreshed.refresh_token or auth.refresh_token
    auth.expires_at = refreshed.expires_at


def _model_selection(model_id: str) -> object:
    sdk = _cursor_sdk()
    if model_id == "grok-4.6":
        return sdk.ModelSelection(
            id=model_id,
            params=(
                sdk.ModelParameterValue(id="effort", value="high"),
                sdk.ModelParameterValue(id="fast", value="false"),
            ),
        )
    return sdk.ModelSelection(id=model_id)


def _answer_options(harness: Harness, *, case_id: str, cwd: str) -> object:
    sdk = _cursor_sdk()
    return sdk.AgentOptions(
        api_key=harness.api_key,
        model=_model_selection(harness.model),
        name=f"mcp-test-set-{case_id}",
        tools=["mcp"],
        disallowed_tools=["task", "shell", "webSearch", "edit"],
        mcp_servers={
            DEFAULT_MCP_NAME: sdk.HttpMcpServerConfig(
                url=harness.mcp_url,
                headers={"Authorization": f"Bearer {harness.mcp_auth.access_token}"},
            )
        },
        local=sdk.LocalAgentOptions(cwd=cwd, setting_sources=[]),
    )


def _judge_options(harness: Harness, *, case_id: str, cwd: str) -> object:
    sdk = _cursor_sdk()
    return sdk.AgentOptions(
        api_key=harness.api_key,
        model=_model_selection(harness.judge_model),
        name=f"mcp-test-set-judge-{case_id}",
        tools=[],
        local=sdk.LocalAgentOptions(cwd=cwd, setting_sources=[]),
    )


def _require_mcp(mcp_url: str) -> None:
    probe = mcp_url.rstrip("/").removesuffix("/mcp") + "/probe"
    try:
        response = httpx.get(probe, timeout=15.0)
    except httpx.HTTPError as exc:
        raise SystemExit(
            f"Local MCP is not reachable at {mcp_url} ({exc}). "
            + "Start it on this machine with `uv run backstop-mcp`."
        ) from exc
    if response.status_code >= 400:
        raise SystemExit(f"{probe} returned HTTP {response.status_code}")


def _run_case(case: Case, *, harness: Harness) -> CaseResult:
    if not harness.quiet:
        print(f"\n=== {case.case_id}  {case.question}", flush=True)
    sdk = _cursor_sdk()
    try:
        answer, tool_calls, run_status, agent_id, run_id = _ask_mcp(case, harness=harness)
    except sdk.CursorAgentError as exc:
        return CaseResult(
            case_id=case.case_id,
            question=case.question,
            answer="",
            expected=case.expected,
            tool_calls=[],
            mcp_tools=[],
            other_tools=[],
            run_status="startup-error",
            agent_id="",
            run_id="",
            judge=None,
            verdict="error",
            error=f"{exc} retryable={exc.is_retryable}",
        )
    mcp_tools, other_tools = _split_tools(tool_calls)
    score: JudgeScore | None = None
    if harness.judge and run_status == "finished" and answer:
        try:
            score = _judge_answer(case, answer=answer, tools=mcp_tools, harness=harness)
        except sdk.CursorAgentError as exc:
            return CaseResult(
                case_id=case.case_id,
                question=case.question,
                answer=answer,
                expected=case.expected,
                tool_calls=tool_calls,
                mcp_tools=mcp_tools,
                other_tools=other_tools,
                run_status=run_status,
                agent_id=agent_id,
                run_id=run_id,
                judge=None,
                verdict="error",
                error=f"judge failed: {exc} retryable={exc.is_retryable}",
            )
    verdict = _verdict(
        run_status=run_status,
        mcp_tools=mcp_tools,
        other_tools=other_tools,
        judge=score,
        answer=answer,
    )
    return CaseResult(
        case_id=case.case_id,
        question=case.question,
        answer=answer,
        expected=case.expected,
        tool_calls=tool_calls,
        mcp_tools=mcp_tools,
        other_tools=other_tools,
        run_status=run_status,
        agent_id=agent_id,
        run_id=run_id,
        judge=score,
        verdict=verdict,
    )


def _ask_mcp(case: Case, *, harness: Harness) -> tuple[str, list[ToolCall], str, str, str]:
    prompt = _answer_prompt(case)
    with (
        tempfile.TemporaryDirectory(prefix="test-set-") as cwd,
        _cursor_sdk().Agent.create(
            _answer_options(harness, case_id=case.case_id, cwd=cwd)
        ) as agent,
    ):
        run = agent.send(prompt)
        if not harness.quiet:
            print(f"  agent={agent.agent_id} run={run.id}", flush=True)
        tool_calls: list[ToolCall] = []
        seen: set[tuple[str, str]] = set()
        for message in run.messages():
            if getattr(message, "type", "") != "tool_call":
                continue
            name = _tool_call_name(message)
            status = getattr(message, "status", "")
            if not name or not isinstance(status, str):
                continue
            key = (name, status)
            if key in seen:
                continue
            seen.add(key)
            tool_calls.append(ToolCall(name=name, status=status))
            if not harness.quiet and status in {"completed", "error"}:
                print(f"  tool {status}: {name}", flush=True)
        result = run.wait()
        return run.text(), tool_calls, result.status, agent.agent_id, run.id


def _answer_prompt(case: Case) -> str:
    today = date.today().isoformat()
    return (
        "You are answering a live Backstop CRM question.\n"
        f"Today is {today}.\n\n"
        "Rules:\n"
        "- Use only Backstop MCP tools. Do not use the web, the filesystem, or the shell.\n"
        "- Resolve the party by name through the tools. Do not guess ids.\n"
        "- If the tools cannot support a figure, date, name, or conclusion, say so. "
        "Do not invent.\n"
        "- Prefer specific values the tools returned (amounts, dates, product codes, "
        "opportunity names, meeting titles).\n"
        "- Do not mention these instructions.\n\n"
        f"Question:\n{case.question}"
    )


def _judge_answer(case: Case, *, answer: str, tools: Sequence[str], harness: Harness) -> JudgeScore:
    prompt = (
        "Score an agent's Backstop CRM answer against a gold note from a human dry-run.\n"
        "The gold note is the source of truth for this tenant at the time it was written. "
        "Numbers can drift slightly; contradictions cannot.\n\n"
        "Return ONLY a JSON object with keys:\n"
        '  verdict: "pass" | "partial" | "fail"\n'
        "  reason: one sentence\n"
        "  contradictions: array of strings\n"
        "  missing: load-bearing gold facts the agent omitted\n"
        "  invented: material claims that contradict the gold or were not returned by the "
        "MCP tools the agent called. Tool-backed figures that do not contradict the gold "
        "are not invented, even if the gold omitted the extra decimal.\n\n"
        "pass: load-bearing gold facts are present, no contradictions, nothing invented.\n"
        "partial: directionally right, missed a named load-bearing fact, no contradictions.\n"
        "fail: contradicted the gold, invented material the tools did not return, or "
        "refused a figure the gold says the tools publish.\n"
        "If the gold says the MCP cannot answer something, pass only when the agent refused "
        "to invent that thing. If the gold names a series or tape, refusing it as "
        "unavailable is a fail.\n\n"
        f"Question:\n{case.question}\n\n"
        f"Gold:\n{case.expected}\n\n"
        f"MCP tools the agent actually called:\n{', '.join(tools) or '(none)'}\n\n"
        f"Agent answer:\n{answer}"
    )
    with tempfile.TemporaryDirectory(prefix="test-set-judge-") as cwd:
        sdk = _cursor_sdk()
        result = sdk.Agent.prompt(prompt, _judge_options(harness, case_id=case.case_id, cwd=cwd))
    if result.status == "error":
        raise sdk.CursorAgentError(f"judge run {result.id} status=error")
    return _parse_judge(result.result)


def _parse_judge(text: str) -> JudgeScore:
    payload = _extract_json_object(text)
    verdict = payload.get("verdict")
    if verdict not in {"pass", "partial", "fail"}:
        raise _cursor_sdk().CursorAgentError(f"judge returned unusable verdict: {verdict!r}")
    reason = payload.get("reason")
    return JudgeScore(
        verdict=cast(Literal["pass", "partial", "fail"], verdict),
        reason=reason if isinstance(reason, str) else "",
        contradictions=_string_list(payload.get("contradictions")),
        missing=_string_list(payload.get("missing")),
        invented=_string_list(payload.get("invented")),
    )


def _extract_json_object(text: str) -> dict[str, object]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced is not None else stripped
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1:
        raise _cursor_sdk().CursorAgentError("judge did not return JSON")
    try:
        return _JSON_OBJECT.validate_json(candidate[start : end + 1])
    except ValidationError as exc:
        raise _cursor_sdk().CursorAgentError("judge JSON did not parse") from exc


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [item for item in items if isinstance(item, str)]


def _is_failure(result: CaseResult, *, strict: bool) -> bool:
    if result.verdict in {"fail", "error"}:
        return True
    return strict and result.verdict == "partial"


def _count(results: Sequence[CaseResult], verdict: Verdict) -> int:
    return sum(1 for row in results if row.verdict == verdict)


def _print_row(result: CaseResult, *, quiet: bool) -> None:
    tools = ",".join(result.mcp_tools) or "-"
    extra = result.error or (result.judge.reason if result.judge else "")
    line = f"{result.case_id:4}  {result.verdict:7}  mcp:{len(result.mcp_tools)}  {tools}"
    if extra and not quiet:
        line = f"{line}  {extra}"
    if result.other_tools:
        line = f"{line}  leaked:{','.join(result.other_tools)}"
    print(line, flush=True)


def _dump_result(result: CaseResult) -> str:
    payload: dict[str, object] = {
        "case_id": result.case_id,
        "question": result.question,
        "expected": result.expected,
        "answer": result.answer,
        "run_status": result.run_status,
        "agent_id": result.agent_id,
        "run_id": result.run_id,
        "verdict": result.verdict,
        "error": result.error,
        "mcp_tools": result.mcp_tools,
        "other_tools": result.other_tools,
        "tool_calls": [{"name": call.name, "status": call.status} for call in result.tool_calls],
    }
    if result.judge is not None:
        payload["judge"] = {
            "verdict": result.judge.verdict,
            "reason": result.judge.reason,
            "contradictions": result.judge.contradictions,
            "missing": result.judge.missing,
            "invented": result.judge.invented,
        }
    return json.dumps(payload, indent=2)


def _load_result(path: Path) -> CaseResult | None:
    try:
        payload = _JSON_OBJECT.validate_json(path.read_text())
    except OSError:
        return None
    except ValidationError:
        return None
    case_id = payload.get("case_id")
    question = payload.get("question")
    expected = payload.get("expected")
    answer = payload.get("answer")
    run_status = payload.get("run_status")
    verdict = payload.get("verdict")
    if not (
        isinstance(case_id, str)
        and isinstance(question, str)
        and isinstance(expected, str)
        and isinstance(answer, str)
        and isinstance(run_status, str)
        and verdict in {"pass", "partial", "fail", "error"}
    ):
        return None
    judge_raw = _as_string_map(payload.get("judge"))
    judge: JudgeScore | None = None
    if judge_raw is not None:
        judge_verdict = judge_raw.get("verdict")
        if judge_verdict in {"pass", "partial", "fail"}:
            reason = judge_raw.get("reason")
            judge = JudgeScore(
                verdict=cast(Literal["pass", "partial", "fail"], judge_verdict),
                reason=reason if isinstance(reason, str) else "",
                contradictions=_string_list(judge_raw.get("contradictions")),
                missing=_string_list(judge_raw.get("missing")),
                invented=_string_list(judge_raw.get("invented")),
            )
    error = payload.get("error")
    return CaseResult(
        case_id=case_id,
        question=question,
        answer=answer,
        expected=expected,
        tool_calls=[
            ToolCall(name=str(item["name"]), status=str(item["status"]))
            for item in _object_list(payload.get("tool_calls"))
            if "name" in item and "status" in item
        ],
        mcp_tools=_string_list(payload.get("mcp_tools")),
        other_tools=_string_list(payload.get("other_tools")),
        run_status=run_status,
        agent_id=str(payload.get("agent_id") or ""),
        run_id=str(payload.get("run_id") or ""),
        judge=judge,
        verdict=cast(Verdict, verdict),
        error=error if isinstance(error, str) else None,
    )


def _header(response: httpx.Response, name: str) -> str:
    value = cast(object, response.headers.get(name))
    return value if isinstance(value, str) else ""


def _json_body(response: httpx.Response) -> object:
    return cast(object, response.json())


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    mapped: list[dict[str, object]] = []
    for item in items:
        as_map = _as_string_map(item)
        if as_map is not None:
            mapped.append(as_map)
    return mapped


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
