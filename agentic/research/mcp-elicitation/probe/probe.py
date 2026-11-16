"""Call MCP tools directly, without an LLM, and log every elicitation the server sends.

    uv run probe.py list <target>                 tools + annotations, no tool calls
    uv run probe.py run <target> [--policy ...]   scenario, then cleanup, then a leftover check
    uv run probe.py sweep <target>                delete leftovers of crashed runs
    uv run probe.py call <target> <tool> '<json>'  one call, for exploring read-only tools

A target is a module in `targets/` exposing `TARGET`, `scenario`, `find_leftovers` and
`delete_leftover`. Everything a scenario creates is named with `probe.name(...)`, so the
leftover check and `sweep` find it by prefix.
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
import uuid
import webbrowser
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx2
import mcp_types as types
from mcp import Client, StdioServerParameters
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import BaseModel, ConfigDict

PREFIX = "elicit-probe"
RUNS_DIR = Path(__file__).parent / "runs"
TOKEN_DIR = Path.home() / ".cache" / "mcp-elicitation-probe"
CALLBACK_PORT = 33418

Policy = Literal["decline", "accept", "cancel"]


class Target(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    url: str | None = None
    stdio: StdioServerParameters | None = None
    auth: Literal["none", "oauth", "headers"] = "none"
    headers: Callable[[], dict[str, str]] | None = None
    oauth_scope: str | None = None


class Leftover(BaseModel):
    kind: str
    id: str
    title: str


class CallOutcome(BaseModel):
    tool: str
    is_error: bool
    text: str
    structured: Any = None

    def json_body(self) -> Any:
        if self.structured is not None:
            return self.structured
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            return None


class Recorder:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.elicitations: list[dict[str, Any]] = []

    def event(self, kind: str, **data: Any) -> None:
        record = {"at": datetime.now(UTC).isoformat(), "kind": kind, **data}
        with self.path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        if kind == "elicitation":
            self.elicitations.append(record)
        print(f"[{kind}] {json.dumps(data, default=str)[:400]}", file=sys.stderr)


class Probe:
    def __init__(self, client: Client, recorder: Recorder, run_id: str, policy: Policy) -> None:
        self.client = client
        self.recorder = recorder
        self.run_id = run_id
        self.policy: Policy = policy
        self.current_tool: str | None = None
        self._cleanups: list[tuple[str, Callable[[], Awaitable[None]]]] = []

    @property
    def run_prefix(self) -> str:
        return f"{PREFIX}-{self.run_id}"

    def name(self, label: str) -> str:
        return f"{self.run_prefix}-{label}"

    def on_cleanup(self, label: str, fn: Callable[[], Awaitable[None]]) -> None:
        self._cleanups.append((label, fn))

    async def call(self, tool: str, arguments: dict[str, Any]) -> CallOutcome:
        self.current_tool = tool
        self.recorder.event("call", tool=tool, arguments=arguments, policy=self.policy)
        try:
            result = await self.client.call_tool(tool, arguments)
        except Exception as e:  # noqa: BLE001 — a protocol error is itself a finding to record
            outcome = CallOutcome(tool=tool, is_error=True, text=f"{type(e).__name__}: {e}")
        else:
            text = "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))
            outcome = CallOutcome(
                tool=tool, is_error=bool(result.is_error), text=text, structured=result.structured_content
            )
        finally:
            self.current_tool = None
        self.recorder.event("result", tool=tool, is_error=outcome.is_error, text=outcome.text[:2000])
        return outcome

    async def run_cleanups(self) -> list[str]:
        """Run cleanups newest-first; a cleanup's own confirmation prompts are accepted."""
        failures = []
        self.policy = "accept"
        for label, fn in reversed(self._cleanups):
            try:
                await fn()
                self.recorder.event("cleanup", label=label, ok=True)
            except Exception as e:  # noqa: BLE001 — keep cleaning up the rest
                failures.append(label)
                self.recorder.event("cleanup", label=label, ok=False, error=f"{type(e).__name__}: {e}")
        return failures


def fill_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    def value_for(prop: dict[str, Any]) -> Any:
        if "default" in prop:
            return prop["default"]
        if prop.get("enum"):
            return prop["enum"][0]
        if prop.get("oneOf"):
            return prop["oneOf"][0].get("const")
        match prop.get("type"):
            case "boolean":
                return True
            case "integer" | "number":
                return prop.get("minimum", 0)
            case "array":
                items = prop.get("items", {})
                options = items.get("enum") or [o.get("const") for o in items.get("anyOf", [])]
                return options[:1]
            case _:
                return PREFIX

    return {key: value_for(prop) for key, prop in schema.get("properties", {}).items()}


def elicitation_handler(probe_ref: list[Probe], recorder: Recorder):
    async def handle(_context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
        probe = probe_ref[0] if probe_ref else None
        policy: Policy = probe.policy if probe else "decline"
        recorder.event(
            "elicitation",
            tool=probe.current_tool if probe else None,
            params=params.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        if policy != "accept":
            response = types.ElicitResult(action=policy)
        elif isinstance(params, types.ElicitRequestURLParams):
            webbrowser.open(params.url)
            response = types.ElicitResult(action="accept")
        else:
            response = types.ElicitResult(action="accept", content=fill_from_schema(params.requested_schema))
        recorder.event("elicitation_response", response=response.model_dump(mode="json", exclude_none=True))
        return response

    return handle


class FileTokenStorage:
    def __init__(self, target: str) -> None:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = TOKEN_DIR / f"{target}.json"

    def _load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self, key: str, value: BaseModel) -> None:
        data = self._load() | {key: value.model_dump(mode="json", exclude_none=True)}
        self.path.write_text(json.dumps(data))
        self.path.chmod(0o600)

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._load().get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._save("tokens", tokens)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._load().get("client_info")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._save("client_info", client_info)


async def open_browser(url: str) -> None:
    print(f"Opening browser for sign-in:\n  {url}", file=sys.stderr)
    webbrowser.open(url)


async def wait_for_oauth_callback() -> AuthorizationCodeResult:
    received: asyncio.Future[AuthorizationCodeResult] = asyncio.get_running_loop().create_future()

    async def on_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = (await reader.readline()).decode()
        query = parse_qs(urlparse(request_line.split(" ")[1]).query)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nSigned in. You can close this tab.")
        await writer.drain()
        writer.close()
        if "code" in query and not received.done():
            received.set_result(AuthorizationCodeResult(code=query["code"][0], state=query.get("state", [None])[0]))

    server = await asyncio.start_server(on_connection, "127.0.0.1", CALLBACK_PORT)
    async with server:
        return await asyncio.wait_for(received, timeout=300)


def build_transport(target: Target) -> Any:
    if target.stdio is not None:
        return target.stdio
    assert target.url is not None, f"target {target.name} needs a url or stdio"
    match target.auth:
        case "none":
            return target.url
        case "headers":
            assert target.headers is not None, f"target {target.name} uses header auth without headers"
            http = httpx2.AsyncClient(headers=target.headers(), timeout=60)
        case "oauth":
            provider = OAuthClientProvider(
                server_url=target.url,
                client_metadata=OAuthClientMetadata(
                    client_name="mcp-elicitation-probe",
                    redirect_uris=[f"http://localhost:{CALLBACK_PORT}/callback"],
                    grant_types=["authorization_code", "refresh_token"],
                    response_types=["code"],
                    token_endpoint_auth_method="none",
                    scope=target.oauth_scope,
                ),
                storage=FileTokenStorage(target.name),
                redirect_handler=open_browser,
                callback_handler=wait_for_oauth_callback,
            )
            http = httpx2.AsyncClient(auth=provider, timeout=60)
    return streamable_http_client(target.url, http_client=http)


async def connect(
    stack: AsyncExitStack, target: Target, recorder: Recorder, probe_ref: list[Probe], *, elicitation: bool, mode: str
) -> Client:
    client = Client(
        build_transport(target),
        mode=mode,  # pyright: ignore[reportArgumentType] — validated by Client
        elicitation_callback=elicitation_handler(probe_ref, recorder) if elicitation else None,
        client_info=types.Implementation(name="mcp-elicitation-probe", version="0.0.0"),
    )
    await stack.enter_async_context(client)
    recorder.event(
        "connected",
        protocol_version=client.session.protocol_version,
        elicitation_capability=elicitation,
    )
    return client


async def list_tools(target_module: ModuleType, mode: str) -> None:
    target: Target = target_module.TARGET
    recorder = Recorder(RUNS_DIR / f"{target.name}-tools.jsonl")
    async with AsyncExitStack() as stack:
        client = await connect(stack, target, recorder, [], elicitation=True, mode=mode)
        tools = (await client.list_tools()).tools
    summary = [
        {
            "name": t.name,
            "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None,
            "required": (t.input_schema or {}).get("required", []),
            "params": sorted((t.input_schema or {}).get("properties", {})),
        }
        for t in tools
    ]
    (RUNS_DIR / f"{target.name}-tools.json").write_text(
        json.dumps([t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools], indent=2)
    )
    print(json.dumps(summary, indent=2))


async def run(target_module: ModuleType, policy: Policy, *, elicitation: bool, mode: str) -> int:
    target: Target = target_module.TARGET
    run_id = uuid.uuid4().hex[:8]
    variant = f"{policy if elicitation else 'no-elicitation'}-{mode}"
    recorder = Recorder(RUNS_DIR / f"{target.name}-{run_id}-{variant}.jsonl")
    recorder.event("run", target=target.name, run_id=run_id, policy=policy, elicitation=elicitation, mode=mode)
    probe_ref: list[Probe] = []
    async with AsyncExitStack() as stack:
        client = await connect(stack, target, recorder, probe_ref, elicitation=elicitation, mode=mode)
        probe = Probe(client, recorder, run_id, policy)
        probe_ref.append(probe)
        try:
            await target_module.scenario(probe)
        except Exception as e:  # noqa: BLE001 — record, then still clean up
            recorder.event("scenario_failed", error=f"{type(e).__name__}: {e}")
        finally:
            failures = await probe.run_cleanups()
            leftovers = await target_module.find_leftovers(probe, probe.run_prefix)
            recorder.event("leftovers", items=[l.model_dump() for l in leftovers], cleanup_failures=failures)

    print(f"\nrun {run_id}: {len(recorder.elicitations)} elicitation(s); log: {recorder.path}")
    for e in recorder.elicitations:
        params = e["params"]
        print(f"  - {e['tool']}: [{params.get('mode', 'form')}] {params.get('message', '')[:160]}")
    if leftovers or failures:
        print(f"CLEANUP INCOMPLETE: {[l.title for l in leftovers]}; run `sweep {target.name}`", file=sys.stderr)
        return 1
    return 0


async def sweep(target_module: ModuleType, mode: str) -> int:
    target: Target = target_module.TARGET
    recorder = Recorder(RUNS_DIR / f"{target.name}-sweep.jsonl")
    probe_ref: list[Probe] = []
    async with AsyncExitStack() as stack:
        client = await connect(stack, target, recorder, probe_ref, elicitation=True, mode=mode)
        probe = Probe(client, recorder, "sweep", "accept")
        probe_ref.append(probe)
        leftovers = await target_module.find_leftovers(probe, PREFIX)
        for leftover in leftovers:
            await target_module.delete_leftover(probe, leftover)
            recorder.event("swept", **leftover.model_dump())
        remaining = await target_module.find_leftovers(probe, PREFIX)
    print(f"swept {len(leftovers)}, remaining {len(remaining)}")
    return 1 if remaining else 0


async def call_once(target_module: ModuleType, tool: str, arguments: dict[str, Any], mode: str) -> None:
    target: Target = target_module.TARGET
    recorder = Recorder(RUNS_DIR / f"{target.name}-calls.jsonl")
    probe_ref: list[Probe] = []
    async with AsyncExitStack() as stack:
        client = await connect(stack, target, recorder, probe_ref, elicitation=True, mode=mode)
        probe = Probe(client, recorder, "call", "decline")
        probe_ref.append(probe)
        outcome = await probe.call(tool, arguments)
    print(outcome.text)


def load_dotenv(path: Path) -> None:
    """Credentials for cleanup live in a gitignored `.env` next to this script."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def main() -> None:
    load_dotenv(Path(__file__).parent / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["list", "run", "sweep", "call"])
    parser.add_argument("target")
    parser.add_argument("tool", nargs="?")
    parser.add_argument("arguments", nargs="?", default="{}")
    parser.add_argument("--policy", choices=["decline", "accept", "cancel"], default="decline")
    parser.add_argument("--no-elicitation", action="store_true", help="do not declare the elicitation capability")
    parser.add_argument("--mode", default="auto", help="auto | legacy | 2026-07-28")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))
    module = importlib.import_module(f"targets.{args.target.replace('-', '_')}")
    match args.command:
        case "list":
            asyncio.run(list_tools(module, args.mode))
        case "run":
            sys.exit(asyncio.run(run(module, args.policy, elicitation=not args.no_elicitation, mode=args.mode)))
        case "sweep":
            sys.exit(asyncio.run(sweep(module, args.mode)))
        case "call":
            assert args.tool, "call needs a tool name"
            asyncio.run(call_once(module, args.tool, json.loads(args.arguments), args.mode))


if __name__ == "__main__":
    main()
