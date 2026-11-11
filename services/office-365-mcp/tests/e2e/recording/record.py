# pyright: reportPrivateUsage=false
"""Records a scenario's chain through the real app and tools against Microsoft Graph or the
stand-in, scrubs it, lints it, replays it through the runner, and writes the fixture.

  GRAPH_TOKEN=... SEED_UPNS=... python -m tests.e2e.recording.record uc-02-01 --target graph
  python -m tests.e2e.recording.record uc-02-01 --target stand-in [--dry-run] [--allow-writes]

The chain comes from the scenario's entry in features/*.calls.yaml, changed by its variant in
recorded.calls.yaml. A tool case of cases/*.yaml names its own chain, persona and fixture. The
recording user is the persona's position of SEED_UPNS, position 1 by default. The token goes into
the Authorization header of requests to graph.microsoft.com and nowhere else; the app itself only
ever holds the runner's synthetic token. Raw answers stay in memory. Exit 0 when written, 1 when
written but the variant's expect does not hold, 2 when refused (nothing written)."""

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, override
from urllib.parse import quote, unquote

import httpx
import pytest
import respx
import yaml
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport

import tests.e2e.test_scenarios as runner
from tests.conftest import RecordedSleeps
from tests.e2e.recording import stand_in as stand_in_graph
from tests.e2e.recording.cases import CASES, case_entries
from tests.e2e.recording.families import load
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
    LARGE_BODY,
    SYNTHETIC_DOMAIN,
    Fixture,
    Hop,
    Identities,
    Recording,
    Target,
    files_of,
    load_corpus,
    mapped_guid,
    scrub,
)
from tests.e2e.recording.stand_in import StandIn
from tests.e2e.test_scenarios import (
    _OBO_TOKEN,
    _SELECTOR,
    _SYMBOL,
    Json,
    Person,
    Replay,
    _asked,
    _step,
    build_server,
    entries,
    generated,
    items,
    mapping,
    patch_obo,
    resolved,
    select,
)

HERE = Path(__file__).parent
RECORDED = HERE / "recorded.calls.yaml"
STAND_IN_OUT = Path(tempfile.gettempdir()) / "office-365-mcp-stand-in"
REFUSED = HERE.parents[2] / ".record-all" / "refused"
GRAPH = f"https://{GRAPH_HOST}/v1.0"
_TRANSIENT = frozenset({429, 503, 504})
_SCOPE = re.compile(r"[A-Za-z]+(?:\.[A-Za-z]+)+")
_MAX_GAP = 600
_MAX_WAIT = 60
_PERSONA = re.compile(r"persona:[a-z]+(?:\.[a-z]+)?|env:SEED_[A-Z]+_UPN")
_PERSONAS = 3
_REPLACED = re.compile(
    r"synthetic text \d+|user-\d+@example\.test|user_\d+_example_test|host-\d+\."
)

type Send = Callable[[httpx.AsyncBaseTransport, httpx.Request], Awaitable[httpx.Response]]


@dataclass(frozen=True)
class Plan:
    scenario: str
    fixture: str
    steps: tuple[Json, ...]
    case: bool = False
    persona: int = 1
    destructive: bool = False
    reseed: tuple[str, ...] = ()
    external: bool = False
    needs: tuple[str, ...] = ()
    cap: int = 0
    scopes: tuple[str, ...] = ()
    gap: int = 0
    reseed_personas: tuple[int, ...] = ()
    deferred: str = ""

    @property
    def literals(self) -> frozenset[str]:
        given = [_literal_args(s) for s in self.steps]
        found = [
            v for _, v in strings(given) if not v.startswith("$") and 4 <= len(v) <= LARGE_BODY
        ]
        return frozenset(one for v in found for one in (v, str(resolved(v, ()))))

    @property
    def tokens(self) -> frozenset[str]:
        return frozenset(found[0] for found in _SYMBOL.finditer(json.dumps(self.steps)))

    @property
    def personas(self) -> frozenset[int]:
        return frozenset(persona_of(step, self.persona) for step in self.steps)


@dataclass(frozen=True, repr=False)
class Outcome:
    recording: Recording
    fixture: Fixture
    report: list[str]
    unmet: list[str]

    @override
    def __repr__(self) -> str:
        return f"Outcome({self.recording.scenario}, {len(self.unmet)} unmet)"


def catalogs(cases: Path | None = None) -> tuple[dict[str, Json], dict[str, Json]]:
    case = dict(case_entries(cases or CASES))
    return dict(entries()) | case, case


def resolve(
    scenario: str,
    recorded: Path = RECORDED,
    cases: Path | None = None,
    loaded: tuple[dict[str, Json], dict[str, Json]] | None = None,
) -> Plan:
    found, case = loaded or catalogs(cases)
    if scenario not in found:
        raise Refused(f"{scenario} is not an entry of features/*.calls.yaml or of cases/*.yaml")
    variants = mapping(cast("object", yaml.safe_load(recorded.read_text())) or {})
    variant: Json = mapping(variants.get(scenario, {})) if scenario not in case else {}
    overrides = cast("Mapping[object, object]", variant)
    chain = items(found[scenario]["chain"])
    steps = tuple(
        {**mapping(step), **mapping(overrides.get(n, {}))} for n, step in enumerate(chain, 1)
    )
    spec: Json = case.get(scenario, {})
    scopes = tuple(map(str, cast("list[object]", spec.get("scopes", []))))
    gap = int(cast("int", spec.get("gap", load().gaps.get(tool_of(steps[-1]), 0))))
    if bad := [name for name in scopes if not _SCOPE.fullmatch(name)]:
        raise Refused(f"{scenario}: {bad} is not a Graph permission name such as Group.Read.All")
    if not 0 <= gap <= _MAX_GAP:
        raise Refused(f"{scenario}: the gap must be within 0..{_MAX_GAP} seconds")
    if bad := [
        n
        for n, step in enumerate(steps, 1)
        if not 1 <= int(cast("int", step.get("wait_seconds", 1))) <= _MAX_WAIT
    ]:
        raise Refused(f"{scenario}: step {bad[0]} waits outside 1..{_MAX_WAIT} seconds")
    if bad := [n for n, step in enumerate(steps, 1) if not 1 <= persona_of(step, 1) <= _PERSONAS]:
        raise Refused(f"{scenario}: step {bad[0]} runs as a persona outside 1..{_PERSONAS}")
    deferred = spec.get("deferred", "")
    if not isinstance(deferred, str) or ("deferred" in spec and not deferred.strip()):
        raise Refused(f"{scenario}: deferred is a reason in words, not {deferred!r}")
    default = f"rec-tool-{scenario}" if spec else f"rec-{scenario}"
    phases, order = reseed_of(spec)
    if bad := [one for one in order if not 1 <= one <= _PERSONAS]:
        raise Refused(f"{scenario}: reseed personas {bad} are not within 1..{_PERSONAS}")
    return Plan(
        scenario,
        str((spec or variant).get("fixture", default)),
        steps,
        bool(spec),
        int(cast("int", spec.get("persona", 1))),
        bool(spec.get("destructive", False)),
        phases,
        bool(spec.get("external", False)),
        tuple(map(str, cast("list[object]", spec.get("needs", [])))),
        int(cast("int", spec.get("cap", 0))),
        scopes,
        gap,
        order,
        deferred,
    )


def reseed_of(spec: Json) -> tuple[tuple[str, ...], tuple[int, ...]]:
    wanted = spec.get("reseed", [])
    if not isinstance(wanted, Mapping):
        return tuple(map(str, cast("list[object]", wanted))), ()
    found = cast("Json", wanted)
    phases = tuple(map(str, cast("list[object]", found.get("phases", []))))
    return phases, tuple(
        int(cast("int", one)) for one in cast("list[object]", found.get("personas", []))
    )


def guard_for(
    upns: Sequence[str],
    plan: Plan,
    allow_writes: bool,
    cap: int,
    extras: Mapping[str, str] | None = None,
) -> Guard:
    if not 1 <= plan.persona <= len(upns):
        raise Refused(f"{plan.scenario}: persona {plan.persona} is not within 1..{len(upns)}")
    wanted = plan.cap or cap
    if not 1 <= wanted <= MAX_CAP:
        raise Refused(f"{plan.scenario}: the request cap must be within 1..{MAX_CAP}")
    return Guard(
        upns[plan.persona - 1],
        frozenset(upns),
        allow_writes,
        wanted,
        people=frozenset(f"persona:{persona.key}.id" for persona in load_corpus().personas),
        extras=extras or {},
    )


def persona_guards(
    upns: Sequence[str], plan: Plan, guard: Guard, extras: Mapping[str, str] | None = None
) -> dict[int, Guard]:
    guards = {plan.persona: guard}
    for who in sorted(plan.personas - {plan.persona}):
        guards[who] = guard_for(
            upns, replace(plan, persona=who), guard.allow_writes, guard.cap, extras
        )
        guards[who].counter = guard.counter
    return guards


def dry_run_lines(
    upns: Sequence[str],
    plan: Plan,
    allow_writes: bool,
    cap: int,
    extras: Mapping[str, str] | None = None,
) -> list[str]:
    guard = guard_for(upns, plan, allow_writes, cap, extras)
    return describe(
        plan, guard, planned_values(upns, extras), persona_guards(upns, plan, guard, extras)
    )


def persona_of(step: Json, default: int) -> int:
    return int(cast("int", step.get("as", default)))


def tool_of(step: Json) -> str:
    return str(step.get("pick", step.get("tool")))


def synthetic_extra(name: str) -> str:
    return f"{name.removeprefix('SEED_').removesuffix('_UPN').lower()}@{SYNTHETIC_DOMAIN}"


def persona_values(
    upns: Sequence[str],
    ids: Mapping[str, str],
    *,
    synthetic: bool,
    extras: Mapping[str, str] | None = None,
) -> dict[str, str]:
    found = {
        f"env:{name}": synthetic_extra(name) if synthetic else address
        for name, address in (extras or {}).items()
    }
    for persona in load_corpus().personas:
        if persona.index > len(upns):
            continue
        key = f"persona:{persona.key}"
        found[key] = f"{persona.key}@example.test" if synthetic else upns[persona.index - 1]
        found[f"{key}.name"] = persona.display_name
        if persona.key in ids:
            found[f"{key}.id"] = mapped_guid(ids[persona.key]) if synthetic else ids[persona.key]
    return found


def with_personas(value: object, values: Mapping[str, str]) -> object:
    if isinstance(value, str):

        def one(found: re.Match[str]) -> str:
            if found[0] not in values:
                raise Refused(
                    f"{found[0]} names no test user, or a user whose id was not read, "
                    + "or an address variable that is not set"
                )
            return values[found[0]]

        return _PERSONA.sub(one, value)
    if isinstance(value, list):
        return [with_personas(item, values) for item in cast("list[object]", value)]
    if isinstance(value, Mapping):
        return {key: with_personas(one, values) for key, one in cast("Json", value).items()}
    return value


def uses_ids(plan: Plan) -> bool:
    return any(
        found.endswith(".id")
        for found in cast("list[str]", _PERSONA.findall(json.dumps(plan.steps)))
    )


def planned_values(upns: Sequence[str], extras: Mapping[str, str] | None = None) -> dict[str, str]:
    ids = {persona.key: f"persona:{persona.key}.id" for persona in load_corpus().personas}
    named = {**{name: synthetic_extra(name) for name in load().address_uses}, **(extras or {})}
    return persona_values(upns, ids, synthetic=False, extras=named)


def _literal_args(step: Json, values: Mapping[str, str] | None = None) -> dict[str, object]:
    given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
    return {
        key: generated(value if values is None else with_personas(value, values))
        for key, value in given.items()
        if not str(value).startswith("$")
    }


def check(
    plan: Plan,
    guard: Guard,
    values: Mapping[str, str] | None = None,
    by_persona: Mapping[int, Guard] | None = None,
) -> list[str]:
    refusals: list[str] = []
    for number, step in enumerate(plan.steps, 1):
        if "fault" in step:
            refusals.append(f"step {number}: a fault is synthetic and is never recorded")
        one = (by_persona or {}).get(persona_of(step, plan.persona), guard)
        refusal = one.refuses_call(tool_of(step), _literal_args(step, values))
        refusals += [f"step {number}: {refusal}"] if refusal else []
    replies = [
        mapping(step.get("args", {})).get("status")
        for step in plan.steps
        if tool_of(step) == "outlook_set_automatic_reply"
    ]
    if "scheduled" in replies and not (
        tool_of(plan.steps[-1]) == "outlook_set_automatic_reply" and replies[-1] == "disabled"
    ):
        refusals.append("a scheduled automatic reply needs a last step that sets it to disabled")
    return refusals


def describe(
    plan: Plan,
    guard: Guard,
    values: Mapping[str, str] | None = None,
    by_persona: Mapping[int, Guard] | None = None,
) -> list[str]:
    lines = [f"{plan.scenario} -> fixture {plan.fixture} (dry run, nothing is sent):"]
    for number, step in enumerate(plan.steps, 1):
        given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
        one = (by_persona or {}).get(persona_of(step, plan.persona), guard)
        refusal = one.refuses_call(tool_of(step), _literal_args(step, values))
        verdict = "allowed" if refusal is None else f"REFUSED: {refusal}"
        if "fault" in step:
            verdict = "REFUSED: a fault is synthetic and is never recorded"
        lines.append(f"  step {number}: {tool_of(step)}({json.dumps(given)}) -> {verdict}")
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
        try:
            response = await self.send(transport, sent)
        except httpx.HTTPError:
            self.guard.write_failed = True
            raise
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
    send: Send,
    transport: httpx.AsyncBaseTransport,
    guard: Guard,
    token: str,
    upns: Sequence[str],
    *,
    people: bool = False,
) -> tuple[Identities, dict[str, str]]:
    async def get(path: str, *, required: bool = True) -> Json:
        request = httpx.Request(
            "GET", f"{GRAPH}{path}", headers={"authorization": f"Bearer {token}"}
        )
        if (refusal := guard.refuses_request(request, PREFLIGHT)) is not None:
            raise Refused(f"preflight: {refusal}")
        response = await send(transport, request)
        body = await response.aread()
        if response.status_code != 200 and not required:
            return {}
        if response.status_code != 200:
            raise Refused(
                f"preflight GET {path} answered {response.status_code}; nothing was recorded"
            )
        return mapping(cast("object", json.loads(body)))

    me = await get("/me?$select=id,userPrincipalName,mail,displayName")
    if str(me.get("userPrincipalName", "")).casefold() != guard.allowed_upn.casefold():
        position = upns.index(guard.allowed_upn) + 1
        raise Refused(
            f"GET /me does not answer SEED_UPNS position {position}; nothing was recorded"
        )
    organization = mapping(
        items((await get("/organization?$select=id,displayName,verifiedDomains"))["value"])[0]
    )
    drive = await get("/me/drive?$select=id", required=False)
    guard.me_id = str(me["id"])
    keys = {persona.index: persona.key for persona in load_corpus().personas}
    mine = upns.index(guard.allowed_upn) + 1
    ids = {keys[mine]: guard.me_id}
    for position, upn in enumerate(upns, 1):
        if people and position != mine:
            ids[keys[position]] = str((await get(f"/users/{quote(upn)}?$select=id"))["id"])
    guard.people = frozenset(ids.values())
    guard.drive_ids = frozenset({str(drive["id"])}) if "id" in drive else frozenset[str]()
    names = {str(me.get("displayName") or ""), str(organization.get("displayName") or "")}
    personas = {persona.display_name for persona in load_corpus().personas}
    values = {
        str(me["id"]),
        str(organization["id"]),
        *guard.drive_ids,
        *upns,
        *ids.values(),
        *(str(me[key]) for key in ("userPrincipalName", "mail") if me.get(key)),
        *(str(mapping(d)["name"]) for d in items(organization.get("verifiedDomains", []))),
        *(name for name in names if len(name) >= 5 and name not in personas),
        *{upn.rpartition("@")[2] for upn in upns},
    }
    return Identities(frozenset(values), token), ids


async def capture(
    plan: Plan,
    target: Target,
    *,
    token: str,
    upns: Sequence[str],
    guard: Guard,
    server: FastMCP[None],
    stand_in: StandIn | None,
    extras: Mapping[str, str] | None = None,
    others: Mapping[int, str] | None = None,
) -> tuple[Recording, list[object], dict[str, str]]:
    extras = extras or {}
    guards = persona_guards(upns, plan, guard, extras)
    if refusals := check(plan, guard, planned_values(upns, extras), guards):
        raise Refused(f"{plan.scenario}: refused before any request: " + "; ".join(refusals))
    tokens = {**dict(others or {}), plan.persona: token}
    if missing := sorted(plan.personas - tokens.keys()):
        raise Refused(f"{plan.scenario}: no token for persona {missing[0]}; set GRAPH_TOKEN_<n>")
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
    identities, people = await preflight(send, delegate, guard, token, upns, people=uses_ids(plan))
    for who in sorted(plan.personas - {plan.persona}):
        more, _ = await preflight(
            send, delegate, guards[who], tokens[who], upns, people=uses_ids(plan)
        )
        identities = Identities(identities.values | more.values | {more.token}, identities.token)
    drives = frozenset(drive for one in guards.values() for drive in one.drive_ids)
    for one in guards.values():
        one.drive_ids = drives
    identities = Identities(identities.values | frozenset(extras.values()), identities.token)
    values = persona_values(upns, people, synthetic=False, extras=extras)
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
            for number, written in enumerate(plan.steps, 1):
                step = mapping(with_personas(written, values))
                recorder.tool = tool_of(step)
                who = persona_of(step, plan.persona)
                recorder.guard, recorder.token = guards[who], tokens[who]
                given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
                try:
                    bound = {key: resolved(value, results) for key, value in given.items()}
                except (AssertionError, IndexError, KeyError) as missing:
                    raise Refused(
                        f"{plan.scenario}: step {number} binds a value that the earlier answer"
                        + f" does not have: {unbound(given, results)}"
                    ) from missing
                if (refusal := recorder.guard.refuses_call(recorder.tool, bound)) is not None:
                    raise Refused(
                        _redacted(
                            f"{plan.scenario}: refused before step {number}: {refusal}", secrets
                        )
                    )
                if "wait_seconds" in step:
                    await asyncio.sleep(int(cast("int", step["wait_seconds"])))
                failure = ""
                try:
                    outcome = await _step(
                        client, recorder, Person(), RecordedSleeps(), number, _bare(step), results
                    )
                    if outcome is None and "tool_error" not in mapping(step.get("expect", {})):
                        failure = "the tool answered with an error"
                    results.append(outcome)
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
        waits = [
            int(value)
            for hop in recorder.hops
            if hop.status in _TRANSIENT
            for name, value in hop.headers
            if name.lower() == "retry-after" and value.isdigit()
        ]
        raise Refused(
            f"{plan.scenario}: transient answers {transient} were captured; faults stay "
            + "synthetic, so record again."
            + f" retry-after {max(waits, default=0)}"
        )
    corpus = load_corpus()
    personas = {
        upns[p.index - 1].casefold(): p.key for p in corpus.personas if p.index <= len(upns)
    } | {
        address.casefold(): synthetic_extra(name).split("@")[0] for name, address in extras.items()
    }
    recording = Recording(
        plan.scenario,
        plan.fixture,
        target,
        recorded_at,
        tuple(recorder.hops),
        identities,
        personas,
        plan.literals,
        plan.tokens,
    )
    return recording, results, people


def unbound(given: Json, results: Sequence[object]) -> str:
    for _, text in strings(given):
        if not text.startswith("$"):
            continue
        root, _, path = text[1:].partition(".")
        try:
            _ = resolved(text, results)
        except AssertionError, IndexError, KeyError:
            try:
                answer = results[-1] if root == "prev" else results[int(root) - 1]
                empty = select(answer, path.rpartition("[")[0]) == []
            except AssertionError, IndexError, KeyError:
                empty = False
            return f"{text} reads an empty list" if empty else f"{text} reads no value"
    return "no selector"


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
        index, field_name, _, name = found.groups()
        if field_name is not None:
            parts.append(r"\[\d+\]")
        elif index is not None:
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
    plan: Plan, fixture: Fixture, server: FastMCP[None], values: Mapping[str, str]
) -> tuple[list[object], list[str], list[str]]:
    replay = Replay([mapping(one) for one in fixture.interactions])
    outcomes: list[object] = []
    broken: list[str] = []
    unmet: list[str] = []
    with tempfile.TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
        for name, body in files_of(fixture).items():
            (Path(folder) / name).parent.mkdir(parents=True, exist_ok=True)
            _ = (Path(folder) / name).write_bytes(body)
        patch.setattr(runner, "HERE", Path(folder))
        patch_obo(patch)
        with respx.mock(assert_all_mocked=True) as graph:
            _ = graph.route().mock(side_effect=replay)
            async with Client(
                FastMCPTransport(server), elicitation_handler=Person(), mode="legacy"
            ) as client:
                for number, written in enumerate(plan.steps, 1):
                    step = mapping(with_personas(written, values))
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
    unused = [n for n in range(len(fixture.interactions)) if n not in replay.seen]
    broken += [
        "interaction {} ({} {}) is never reached on replay".format(
            n + 1, fixture.interactions[n]["method"], fixture.interactions[n]["path"]
        )
        for n in unused
    ]
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
    refused: Path | None = None,
    extras: Mapping[str, str] | None = None,
    others: Mapping[int, str] | None = None,
) -> Outcome:
    if not upns:
        raise Refused("SEED_UPNS is not set; the recorder records only its position 1")
    guard = guard_for(upns, plan, allow_writes, cap, extras)
    server = build_server()
    logging.getLogger().setLevel(logging.ERROR)
    recording, live, people = await capture(
        plan,
        target,
        token=token,
        upns=upns,
        guard=guard,
        server=server,
        stand_in=stand_in,
        extras=extras,
        others=others,
    )
    secrets = sorted(recording.identities.everything())
    fixture = scrub(recording)
    findings = lint_files(files_of(fixture), recording.identities.everything())
    if findings:
        raise _refuse(
            f"{plan.scenario}: the lint found {len(findings)} leak(s), nothing was written:\n  "
            + "\n  ".join(findings),
            fixture,
            plan.scenario,
            refused,
        )
    synthetic = persona_values(upns, people, synthetic=True, extras=extras)
    replayed, broken, unmet = await replay_check(plan, fixture, server, synthetic)
    if broken:
        raise _refuse(
            _redacted(
                f"{plan.scenario}: the scrubbed fixture does not replay, nothing was written:\n  "
                + "\n  ".join(broken),
                secrets,
            ),
            fixture,
            plan.scenario,
            refused,
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
    answered = sum("response_json" in one or "body" in one for one in fixture.interactions)
    report = [
        f"{plan.scenario}: {len(recording.hops)} requests -> {len(fixture.interactions)} "
        + f"interactions, {answered} bodies, lint clean, replay clean",
        "  scrub: " + ", ".join(f"{k} {v}" for k, v in fixture.counts.items()),
        "  tool output changed by the scrub: " + ", ".join(f"{k} {v}" for k, v in tally.items()),
    ]
    if fixture.dropped:
        report.append("  dropped: " + ", ".join(f"{k} x{v}" for k, v in fixture.dropped.items()))
    return Outcome(recording, fixture, report, unmet)


def _refuse(message: str, fixture: Fixture, case: str, root: Path | None) -> Refused:
    if root is not None:
        shutil.rmtree(root / case, ignore_errors=True)
        (root / case).mkdir(parents=True, mode=0o700)
        _ = write(fixture, root / case)
    return Refused(message)


def write(fixture: Fixture, out: Path) -> list[Path]:
    stale = re.compile(re.escape(fixture.name) + r"\.\d{2}\.")
    old: Path
    for old in (out / "bodies").glob(f"{fixture.name}.*"):
        if stale.match(old.name):
            old.unlink()
    written: list[Path] = []
    for name, body in files_of(fixture).items():
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


def extras_from_environment() -> dict[str, str]:
    found = {
        name: os.environ[name].strip().casefold()
        for name in sorted(os.environ)
        if re.fullmatch(r"SEED_[A-Z]+_UPN", name) and os.environ[name].strip()
    }
    if bad := [name for name, address in found.items() if address.count("@") != 1]:
        raise Refused(f"{bad} must each hold one address")
    return found


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
        extras = {} if stand_in else extras_from_environment()
        secrets += [*upns, *extras.values()]
        plans = [resolve(scenario) for scenario in scenarios]
        if linked and any(plan.case for plan in plans):
            raise Refused("--link does not apply to a tool case; a case has no sidecar entry")
        if cast("bool", arguments.dry_run):
            lines = [
                line
                for plan in plans
                for line in dry_run_lines(upns, plan, allow_writes, cap, extras)
            ]
            print(_redacted("\n".join(lines), secrets))
            return 2 if any("REFUSED" in line for line in lines) else 0
        token = stand_in_graph.TOKEN if stand_in else os.environ.get("GRAPH_TOKEN", "").strip()
        if not token:
            raise Refused("GRAPH_TOKEN is not set (see tests/e2e/recording/README.md)")
        others = (
            {}
            if stand_in
            else {
                n: found
                for n in range(1, _PERSONAS + 1)
                if (found := os.environ.get(f"GRAPH_TOKEN_{n}", "").strip())
            }
        )
        secrets += [token, *others.values()]
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
                    refused=REFUSED,
                    extras=extras,
                    others=others,
                )
            )
            shutil.rmtree(REFUSED / plan.scenario, ignore_errors=True)
            secrets += sorted(outcome.recording.identities.values)
            written = write(outcome.fixture, out)
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
