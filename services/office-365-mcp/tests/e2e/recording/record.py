# pyright: reportPrivateUsage=false
"""Records a scenario's chain through the real app and tools against Microsoft Graph or the
stand-in, scrubs it, lints it, replays it through the runner, and writes the cassette.

  GRAPH_TOKEN=... SEED_UPNS=... python -m tests.e2e.recording.record uc-02-01 --target graph
  python -m tests.e2e.recording.record uc-02-01 --target stand-in [--dry-run] [--allow-writes]

The chain comes from the scenario's entry in features/*.calls.yaml, changed by its variant in
recorded.calls.yaml. The recording user is position 1 of SEED_UPNS. The token goes into the
Authorization header of requests to graph.microsoft.com and nowhere else; the app itself only ever
holds the runner's synthetic token. Raw answers stay in memory. Exit 0 when written, 1 when
written but the variant's expect does not hold, 2 when refused (nothing written)."""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, override
from urllib.parse import unquote

import httpx
import pytest
import respx
import yaml
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport

import tests.e2e.test_scenarios as runner
from tests.conftest import RecordedSleeps
from tests.e2e.recording import stand_in as stand_in_graph
from tests.e2e.recording.guard import (
    DEFAULT_CAP,
    GRAPH_HOST,
    MAX_CAP,
    PREFLIGHT,
    Guard,
    Refused,
    strings,
)
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.scrub import (
    Cassette,
    Hop,
    Identities,
    Recording,
    Target,
    files_of,
    load_corpus,
    scrub,
)
from tests.e2e.recording.stand_in import StandIn
from tests.e2e.test_scenarios import (
    _OBO_TOKEN,
    _SELECTOR,
    Json,
    Person,
    Replay,
    _asked,
    _given,
    _step,
    build_server,
    entries,
    items,
    mapping,
    patch_obo,
    select,
)

HERE = Path(__file__).parent
RECORDED = HERE / "recorded.calls.yaml"
STAND_IN_OUT = Path(tempfile.gettempdir()) / "office-365-mcp-stand-in"
GRAPH = f"https://{GRAPH_HOST}/v1.0"
_TRANSIENT = frozenset({429, 503, 504})
_REPLACED = re.compile(
    r"synthetic text \d+|user-\d+@example\.test|user_\d+_example_test|host-\d+\."
)

type Send = Callable[[httpx.AsyncBaseTransport, httpx.Request], Awaitable[httpx.Response]]


@dataclass(frozen=True)
class Plan:
    scenario: str
    cassette: str
    steps: tuple[Json, ...]

    @property
    def literals(self) -> frozenset[str]:
        given = [{**mapping(s.get("args", {})), **mapping(s.get("bind", {}))} for s in self.steps]
        return frozenset(v for _, v in strings(given) if not v.startswith("$") and len(v) >= 4)


@dataclass(frozen=True, repr=False)
class Outcome:
    recording: Recording
    cassette: Cassette
    report: list[str]
    unmet: list[str]

    @override
    def __repr__(self) -> str:
        return f"Outcome({self.recording.scenario}, {len(self.unmet)} unmet)"


def resolve(scenario: str, recorded: Path = RECORDED) -> Plan:
    found = dict(entries())
    if scenario not in found:
        raise Refused(f"{scenario} is not an entry of features/*.calls.yaml")
    variants = mapping(cast("object", yaml.safe_load(recorded.read_text())) or {})
    variant = mapping(variants.get(scenario, {}))
    overrides = cast("Mapping[object, object]", variant)
    chain = items(found[scenario]["chain"])
    steps = tuple(
        {**mapping(step), **mapping(overrides.get(n, {}))} for n, step in enumerate(chain, 1)
    )
    return Plan(scenario, str(variant.get("cassette", f"rec-{scenario}")), steps)


def _tool(step: Json) -> str:
    return str(step.get("pick", step.get("tool")))


def _literal_args(step: Json) -> dict[str, object]:
    given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
    return {key: value for key, value in given.items() if not str(value).startswith("$")}


def check(plan: Plan, guard: Guard) -> list[str]:
    refusals: list[str] = []
    for number, step in enumerate(plan.steps, 1):
        if "fault" in step:
            refusals.append(f"step {number}: a fault is synthetic and is never recorded")
        refusal = guard.refuses_call(_tool(step), _literal_args(step))
        refusals += [f"step {number}: {refusal}"] if refusal else []
    return refusals


def describe(plan: Plan, guard: Guard) -> list[str]:
    lines = [f"{plan.scenario} -> cassette {plan.cassette} (dry run, nothing is sent):"]
    for number, step in enumerate(plan.steps, 1):
        given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
        refusal = guard.refuses_call(_tool(step), _literal_args(step))
        verdict = "allowed" if refusal is None else f"REFUSED: {refusal}"
        if "fault" in step:
            verdict = "REFUSED: a fault is synthetic and is never recorded"
        lines.append(f"  step {number}: {_tool(step)}({json.dumps(given)}) -> {verdict}")
    return lines


@dataclass(kw_only=True, repr=False)
class Recorder(Replay):
    send: Send
    guard: Guard
    token: str = field(repr=False)
    tool: str = PREFLIGHT
    hops: list[Hop] = field(default_factory=list[Hop])
    refusals: list[str] = field(default_factory=list[str])

    async def hop(
        self, transport: httpx.AsyncBaseTransport, request: httpx.Request
    ) -> httpx.Response:
        self.calls.append((self.step, f"{request.method} {unquote(request.url.path)}"))
        _ = await request.aread()
        refusal = self.guard.refuses_request(request, self.tool)
        graph = request.url.host == GRAPH_HOST
        if (
            refusal is None
            and graph
            and request.headers.get("authorization") != f"Bearer {_OBO_TOKEN}"
        ):
            refusal = "a Graph request does not carry the session's token"
        if refusal is not None:
            self.refusals.append(f"step {self.step} ({self.tool}): {refusal}")
            return httpx.Response(418, request=request)
        headers = (
            {**request.headers, "authorization": f"Bearer {self.token}"}
            if graph
            else request.headers
        )
        sent = httpx.Request(request.method, request.url, headers=headers, content=request.content)
        response = await self.send(transport, sent)
        raw = b"".join([chunk async for chunk in response.aiter_raw()])
        await response.aclose()
        headers_back = tuple(response.headers.multi_items())
        decoded = httpx.Response(response.status_code, headers=headers_back, content=raw).content
        hop = Hop(
            _asked(request),
            str(request.url),
            "authorization" in request.headers,
            response.status_code,
            headers_back,
            decoded,
        )
        self.hops.append(hop)
        location = cast("str | None", response.headers.get("location"))
        self.guard.saw(request, response.status_code, location, _json(decoded))
        return httpx.Response(
            response.status_code,
            headers=headers_back,
            stream=httpx.ByteStream(raw),
            request=request,
        )


def _json(body: bytes) -> object:
    try:
        return cast("object", json.loads(body)) if body else None
    except ValueError:
        return None


def _captured_by(
    recorder: Recorder,
) -> Callable[[httpx.AsyncHTTPTransport, httpx.Request], Awaitable[httpx.Response]]:
    async def captured(
        transport: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        return await recorder.hop(transport, request)

    return captured


def _redacted(text: str, secrets: Sequence[str]) -> str:
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        text = re.sub(re.escape(secret), "<redacted>", text, flags=re.IGNORECASE)
    return re.sub(r"eyJ[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]*)*", "<redacted>", text)


async def preflight(
    send: Send, transport: httpx.AsyncBaseTransport, guard: Guard, token: str, upns: Sequence[str]
) -> Identities:
    async def get(path: str) -> Json:
        request = httpx.Request(
            "GET", f"{GRAPH}{path}", headers={"authorization": f"Bearer {token}"}
        )
        if (refusal := guard.refuses_request(request, PREFLIGHT)) is not None:
            raise Refused(f"preflight: {refusal}")
        response = await send(transport, request)
        body = await response.aread()
        if response.status_code != 200:
            raise Refused(
                f"preflight GET {path} answered {response.status_code}; nothing was recorded"
            )
        return mapping(cast("object", json.loads(body)))

    me = await get("/me?$select=id,userPrincipalName,mail,displayName")
    if str(me.get("userPrincipalName", "")).casefold() != guard.allowed_upn.casefold():
        raise Refused("GET /me does not answer SEED_UPNS position 1; nothing was recorded")
    organization = mapping(
        items((await get("/organization?$select=id,displayName,verifiedDomains"))["value"])[0]
    )
    drive = await get("/me/drive?$select=id")
    guard.me_id, guard.drive_ids = str(me["id"]), frozenset({str(drive["id"])})
    names = {str(me.get("displayName") or ""), str(organization.get("displayName") or "")}
    personas = {persona.display_name for persona in load_corpus().personas}
    values = {
        str(me["id"]),
        str(organization["id"]),
        str(drive["id"]),
        *upns,
        *(str(me[key]) for key in ("userPrincipalName", "mail") if me.get(key)),
        *(str(mapping(d)["name"]) for d in items(organization.get("verifiedDomains", []))),
        *(name for name in names if len(name) >= 5 and name not in personas),
        *{upn.rpartition("@")[2] for upn in upns},
    }
    return Identities(frozenset(values), token)


async def capture(
    plan: Plan,
    target: Target,
    *,
    token: str,
    upns: Sequence[str],
    guard: Guard,
    server: FastMCP[None],
    stand_in: StandIn | None,
) -> tuple[Recording, list[object]]:
    if refusals := check(plan, guard):
        raise Refused(f"{plan.scenario}: refused before any request: " + "; ".join(refusals))
    original = httpx.AsyncHTTPTransport.handle_async_request
    if target == "graph":
        delegate: httpx.AsyncBaseTransport = httpx.AsyncHTTPTransport(http2=True)
        send = cast("Send", original)
    else:
        if stand_in is None:
            raise Refused("the stand-in target needs a stand-in")
        delegate = httpx.ASGITransport(app=stand_in.app())

        async def answered(
            _transport: httpx.AsyncBaseTransport, request: httpx.Request
        ) -> httpx.Response:
            return await delegate.handle_async_request(request)

        send = answered
    identities = await preflight(send, delegate, guard, token, upns)
    secrets = sorted(identities.everything())
    recorder = Recorder(interactions=[], send=send, guard=guard, token=token)
    results: list[object] = []
    recorded_at = datetime.now(UTC)
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        patch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _captured_by(recorder))
        async with Client(
            FastMCPTransport(server), elicitation_handler=Person(), mode="legacy"
        ) as client:
            for number, step in enumerate(plan.steps, 1):
                recorder.tool = _tool(step)
                try:
                    bound = {
                        key: _given(value, results)
                        for key, value in {
                            **mapping(step.get("args", {})),
                            **mapping(step.get("bind", {})),
                        }.items()
                    }
                except (IndexError, KeyError) as missing:
                    raise Refused(
                        f"{plan.scenario}: step {number} binds a value that the earlier answer"
                        + " does not have. A search with no hit yet is the usual cause: wait"
                        + " for the search index, then record again."
                    ) from missing
                if (refusal := guard.refuses_call(recorder.tool, bound)) is not None:
                    raise Refused(
                        _redacted(
                            f"{plan.scenario}: refused before step {number}: {refusal}", secrets
                        )
                    )
                failure = ""
                try:
                    results.append(
                        await _step(
                            client,
                            recorder,
                            Person(),
                            RecordedSleeps(),
                            number,
                            _bare(step),
                            results,
                        )
                    )
                except AssertionError as failed:
                    failure = str(failed)
                if recorder.refusals:
                    raise Refused(
                        _redacted(
                            f"{plan.scenario}: refused before sending: "
                            + "; ".join(recorder.refusals),
                            secrets,
                        )
                    )
                if failure:
                    raise Refused(
                        _redacted(
                            f"{plan.scenario} step {number} failed while recording: {failure}",
                            secrets,
                        )
                    )
    leaked = [h for h in recorder.hops if h.asked["host"] != GRAPH_HOST and h.authorized]
    transient = [f"{h.status} {h.asked['method']}" for h in recorder.hops if h.status in _TRANSIENT]
    if leaked:
        raise Refused(f"{plan.scenario}: a token went to a host that is not Graph")
    if transient:
        raise Refused(
            f"{plan.scenario}: transient answers {transient} were captured; faults stay "
            + "synthetic, so record again"
        )
    corpus = load_corpus()
    personas = {
        upns[p.index - 1].casefold(): p.key for p in corpus.personas if p.index <= len(upns)
    }
    recording = Recording(
        plan.scenario,
        plan.cassette,
        target,
        recorded_at,
        tuple(recorder.hops),
        identities,
        personas,
        plan.literals,
    )
    return recording, results


def _bare(step: Json) -> dict[str, object]:
    bare = {key: value for key, value in step.items() if key != "expect"}
    expect = mapping(step.get("expect", {}))
    return bare | (
        {"expect": {"tool_error": expect["tool_error"]}} if "tool_error" in expect else {}
    )


def leaves(value: object, path: str = "") -> dict[str, object]:
    if isinstance(value, Mapping):
        found: dict[str, object] = {}
        for key, one in cast("Json", value).items():
            found |= leaves(one, f"{path}.{key}" if path else key)
        return found
    if isinstance(value, list):
        found = {}
        for n, one in enumerate(cast("list[object]", value)):
            found |= leaves(one, f"{path}[{n}]")
        return found
    return {path: value}


def changed(live: object, replayed: object) -> dict[str, str]:
    before, after = leaves(live), leaves(replayed)
    kinds: dict[str, str] = {}
    for path in sorted(before.keys() | after.keys()):
        if before.get(path) == after.get(path):
            continue
        now = after.get(path)
        if now is None:
            kinds[path] = "dropped"
        elif isinstance(now, str) and _REPLACED.search(now):
            kinds[path] = "replaced"
        else:
            kinds[path] = "mapped"
    return kinds


def covers(selector: str) -> re.Pattern[str]:
    parts: list[str] = []
    for found in _SELECTOR.finditer(selector):
        index, name = found.groups()
        if index is not None:
            parts.append(r"\[\d+\]" if index == "*" else rf"\[{index}\]")
        else:
            parts.append(("\\." if parts else "") + re.escape(name))
    return re.compile("".join(parts) + r"(?:[.\[].*)?")


def _unmet(number: int, expect: Json, outcome: object, replay: Replay) -> list[str]:
    unmet: list[str] = []
    for path, wanted in mapping(expect.get("result", {})).items():
        try:
            got = select(outcome, path)
        except AssertionError, KeyError, IndexError, TypeError, ValueError:
            got = "(missing)"
        if got != wanted:
            unmet.append(f"step {number}: {path} is {got!r}, the variant expects {wanted!r}")
    if "graph_calls" in expect:
        wanted_calls = mapping(expect["graph_calls"])
        made = replay.counted(number, wanted_calls)
        if made != dict(wanted_calls):
            unmet.append(
                f"step {number}: Graph calls {made}, the variant expects {dict(wanted_calls)}"
            )
    return unmet


async def replay_check(
    plan: Plan, cassette: Cassette, server: FastMCP[None]
) -> tuple[list[object], list[str], list[str]]:
    replay = Replay([mapping(one) for one in cassette.interactions])
    outcomes: list[object] = []
    broken: list[str] = []
    unmet: list[str] = []
    with tempfile.TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
        for name, body in files_of(cassette).items():
            (Path(folder) / name).parent.mkdir(parents=True, exist_ok=True)
            _ = (Path(folder) / name).write_bytes(body)
        patch.setattr(runner, "HERE", Path(folder))
        patch_obo(patch)
        with respx.mock(assert_all_mocked=True) as graph:
            _ = graph.route().mock(side_effect=replay)
            async with Client(
                FastMCPTransport(server), elicitation_handler=Person(), mode="legacy"
            ) as client:
                for number, step in enumerate(plan.steps, 1):
                    try:
                        outcome = await _step(
                            client,
                            replay,
                            Person(),
                            RecordedSleeps(),
                            number,
                            _bare(step),
                            outcomes,
                        )
                    except AssertionError as failed:
                        broken.append(f"step {number}: {failed}")
                        break
                    if replay.unmatched:
                        broken.append(f"step {number}: " + "\n".join(replay.unmatched))
                        break
                    outcomes.append(outcome)
                    unmet += _unmet(number, mapping(step.get("expect", {})), outcome, replay)
    unused = [n for n in range(len(cassette.interactions)) if n not in replay.seen]
    broken += [f"interaction {n + 1} is never reached on replay" for n in unused]
    return outcomes, broken, unmet


async def record(
    plan: Plan,
    target: Target,
    *,
    token: str,
    upns: Sequence[str],
    allow_writes: bool,
    cap: int = DEFAULT_CAP,
    stand_in: StandIn | None = None,
) -> Outcome:
    if not upns:
        raise Refused("SEED_UPNS is not set; the recorder records only its position 1")
    guard = Guard(upns[0], frozenset({upns[0].rpartition("@")[2].casefold()}), allow_writes, cap)
    server = build_server()
    logging.getLogger().setLevel(logging.ERROR)
    recording, live = await capture(
        plan, target, token=token, upns=upns, guard=guard, server=server, stand_in=stand_in
    )
    secrets = sorted(recording.identities.everything())
    cassette = scrub(recording)
    findings = lint_files(files_of(cassette), recording.identities.everything())
    if findings:
        raise Refused(
            f"{plan.scenario}: the lint found {len(findings)} leak(s), nothing was written:\n  "
            + "\n  ".join(findings)
        )
    replayed, broken, unmet = await replay_check(plan, cassette, server)
    if broken:
        raise Refused(
            _redacted(
                f"{plan.scenario}: the scrubbed cassette does not replay, nothing was written:\n  "
                + "\n  ".join(broken),
                secrets,
            )
        )
    kinds: dict[str, str] = {}
    for number, (before, after) in enumerate(zip(live, replayed, strict=True), 1):
        kinds |= {f"step {number}: {path}": kind for path, kind in changed(before, after).items()}
    asserted = [
        f"step {number}: {selector} reads {path.split(': ', 1)[1]} ({kind})"
        for number, step in enumerate(plan.steps, 1)
        for selector in mapping(mapping(step.get("expect", {})).get("result", {}))
        for path, kind in kinds.items()
        if kind != "mapped"
        and path.startswith(f"step {number}: ")
        and covers(selector).fullmatch(path.split(": ", 1)[1])
    ]
    if asserted:
        raise Refused(
            f"{plan.scenario}: the variant's expect asserts on fields the scrub replaced, "
            + "nothing was written:\n  "
            + "\n  ".join(asserted)
        )
    tally = {
        kind: sum(1 for k in kinds.values() if k == kind)
        for kind in ("replaced", "dropped", "mapped")
    }
    report = [
        f"{plan.scenario}: {len(recording.hops)} requests -> {len(cassette.interactions)} "
        + f"interactions, {len(cassette.fixtures)} fixtures, lint clean, replay clean",
        "  scrub: " + ", ".join(f"{k} {v}" for k, v in cassette.counts.items()),
        "  tool output changed by the scrub: " + ", ".join(f"{k} {v}" for k, v in tally.items()),
    ]
    return Outcome(recording, cassette, report, unmet)


def write(cassette: Cassette, out: Path) -> list[Path]:
    stale = re.compile(re.escape(cassette.name) + r"\.\d{2}\.")
    old: Path
    for old in (out / "fixtures").glob(f"{cassette.name}.*"):
        if stale.match(old.name):
            old.unlink()
    written: list[Path] = []
    for name, body in files_of(cassette).items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        _ = (out / name).write_bytes(body)
        written.append(out / name)
    return written


def _span_end(lines: Sequence[str], start: int, indent: int) -> int:
    last = start
    for n in range(start + 1, len(lines)):
        if lines[n].strip() and len(lines[n]) - len(lines[n].lstrip()) <= indent:
            break
        last = n if lines[n].strip() else last
    return last + 1


def link(scenario: str, recorded: Path = RECORDED, features: Path = runner.FEATURES) -> Path:
    text = recorded.read_text()
    wanted = mapping(cast("object", yaml.safe_load(text)) or {})
    if scenario not in wanted:
        raise Refused(f"{scenario} has no block in recorded.calls.yaml")
    source = text.splitlines()
    first = source.index(f"{scenario}:")
    block = [
        f"    {line}" if line else line for line in source[first + 1 : _span_end(source, first, 0)]
    ]
    header = ["    recorded:", *block]
    for sidecar in sorted(features.glob("*.calls.yaml")):
        lines = sidecar.read_text().splitlines()
        if f"{scenario}:" not in lines:
            continue
        start = lines.index(f"{scenario}:")
        end = _span_end(lines, start, 0)
        if "  variants:" not in lines[start:end]:
            lines[end:end] = ["  variants:", *header]
        else:
            variants = lines.index("  variants:", start, end)
            top = _span_end(lines, variants, 2)
            if "    recorded:" in lines[variants:top]:
                old = lines.index("    recorded:", variants, top)
                lines[old : _span_end(lines, old, 4)] = header
            else:
                lines[top:top] = header
        linked = "\n".join(lines) + "\n"
        entry = mapping(mapping(cast("object", yaml.safe_load(linked)))[scenario])
        if mapping(mapping(entry["variants"])["recorded"]) != mapping(wanted[scenario]):
            raise Refused(f"{scenario}: the linked block differs from recorded.calls.yaml")
        _ = sidecar.write_text(linked)
        return sidecar
    raise Refused(f"{scenario} is not an entry of features/*.calls.yaml")


def upns_from_environment() -> tuple[str, ...]:
    upns = tuple(
        one.strip().casefold() for one in os.environ.get("SEED_UPNS", "").split(",") if one.strip()
    )
    if (
        not upns
        or any(upn.count("@") != 1 for upn in upns)
        or len({u.rpartition("@")[2] for u in upns}) != 1
    ):
        raise Refused("SEED_UPNS must list the test users (Mia first) in one domain")
    return upns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("scenarios", nargs="+")
    parser.add_argument("--target", choices=["graph", "stand-in"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--link", action="store_true")
    parser.add_argument("--max-requests", type=int, default=DEFAULT_CAP)
    parser.add_argument("--stand-in-variant", action="append", default=[])
    arguments = parser.parse_args(argv)
    scenarios, variants = (
        cast("list[str]", arguments.scenarios),
        cast("list[str]", arguments.stand_in_variant),
    )
    allow_writes, cap = cast("bool", arguments.allow_writes), cast("int", arguments.max_requests)
    linked, out_dir = cast("bool", arguments.link), cast("Path | None", arguments.out)
    for name in ("httpx", "httpcore", "mcp", "fastmcp"):
        logging.getLogger(name).setLevel(logging.WARNING)
    target = cast("Target", arguments.target)
    secrets: list[str] = []
    try:
        if not 1 <= cap <= MAX_CAP:
            raise Refused(f"--max-requests must be within 1..{MAX_CAP}")
        stand_in = target == "stand-in"
        if linked and (stand_in or out_dir):
            raise Refused("--link needs a graph recording that goes into the repository")
        upns = stand_in_graph.UPNS if stand_in else upns_from_environment()
        secrets += upns
        guard = Guard(upns[0], frozenset({upns[0].rpartition("@")[2].casefold()}), allow_writes)
        plans = [resolve(scenario) for scenario in scenarios]
        if cast("bool", arguments.dry_run):
            lines = [line for plan in plans for line in describe(plan, guard)]
            print(_redacted("\n".join(lines), secrets))
            return 2 if any("REFUSED" in line for line in lines) else 0
        token = stand_in_graph.TOKEN if stand_in else os.environ.get("GRAPH_TOKEN", "").strip()
        if not token:
            raise Refused("GRAPH_TOKEN is not set (see tests/e2e/recording/README.md)")
        secrets.append(token)
        out = out_dir or (STAND_IN_OUT if stand_in else runner.HERE)
        status = 0
        for plan in plans:
            graph = StandIn(frozenset(variants)) if stand_in else None
            outcome = asyncio.run(
                record(
                    plan,
                    target,
                    token=token,
                    upns=upns,
                    allow_writes=allow_writes,
                    cap=cap,
                    stand_in=graph,
                )
            )
            secrets += sorted(outcome.recording.identities.values)
            written = write(outcome.cassette, out)
            print(
                _redacted(
                    "\n".join([*outcome.report, f"  wrote {len(written)} files under {out}"]),
                    secrets,
                )
            )
            if outcome.unmet:
                print(
                    _redacted(
                        "  the variant's expect does not hold on the recording; update "
                        + "recorded.calls.yaml:\n    "
                        + "\n    ".join(outcome.unmet),
                        secrets,
                    )
                )
                status = 1
            elif linked:
                sidecar = link(plan.scenario)
                print(
                    f"  linked {plan.scenario} into {sidecar.name}. Runs now: {len(runner.runs())}."
                    + " Set _MINIMUM_EXECUTABLE to that number."
                )
        return status
    except Refused as refused:
        print(f"refused: {_redacted(str(refused), secrets)}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - never print a traceback, it can carry request data
        print(
            f"recorder: unexpected {type(error).__name__}: {_redacted(str(error), secrets)}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
