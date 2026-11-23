"""Runs the sidecar entries that name a fixture through the real app, middleware and tools, with
Graph answered from `fixtures/`. `features/README.md`, "Running the scenarios", has the keys."""

import functools
import importlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from fnmatch import fnmatch
from html.parser import HTMLParser
from pathlib import Path
from typing import cast, override
from urllib.parse import parse_qsl, unquote

import httpx
import pytest
import respx
import yaml
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, FastMCP
from fastmcp.client.elicitation import ElicitRequestParams, ElicitResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from mcp.types import ElicitRequestFormParams

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig
from office_365_mcp.tools import TOOL_NAMES
from tests.conftest import RecordedSleeps
from tests.graph_fixtures import response

type Json = Mapping[str, object]

HERE = Path(__file__).parent
FEATURES = HERE.parents[1] / "features"
_MINIMUM_EXECUTABLE = 34
_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"
_REQUEST_HEADERS = ("prefer", "consistencylevel")
_DATETIME = r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?"
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_SYMBOL = re.compile(
    rf"~(yesterday|today|tomorrow|day[+-]\d+|next(?:{'|'.join(_WEEKDAYS)})(?:[+-]\d+)?)"
)
_SIZED = re.compile(r"<generated:(\d+)>")
MAX_GENERATED = 20_000_000
_GENERATED_KEYS = frozenset({"transactionId", "externalId"})
_TODAY = datetime.now(UTC).date()
_DAYS = {
    word: _TODAY + timedelta(n) for n, word in enumerate(("yesterday", "today", "tomorrow"), -1)
}
_NEXT = re.compile(r"next([A-Za-z]+)([+-]\d+)?")
_OFFSET = re.compile(r"day([+-]\d+)")
_SELECTOR = re.compile(r"\[(\d+|\*)\]|\[(\w+)=([^\]]*)\]|\.?([^.\[]+)")
_MARKUP = re.compile(r"([a-z][a-z0-9]*)\[([\w\-]+)\]")
_REFERENCE = re.compile(r"(?:tools|shared|graph_client)(?:\.\w+)+")


def day_named(word: str, today: date | None = None) -> date:
    """A day symbol of a case or a fixture. `nextMonday` is the next Monday on or after tomorrow;
    `+N` or `-N` after it moves that many days. `day+N` is N days from today."""
    today = today or _TODAY
    if offset := _OFFSET.fullmatch(word):
        return today + timedelta(int(offset[1]))
    found = _NEXT.fullmatch(word)
    if found is None:
        return today + timedelta(("yesterday", "today", "tomorrow").index(word) - 1)
    first = today + timedelta(1)
    return first + timedelta((_WEEKDAYS.index(found[1]) - first.weekday()) % 7 + int(found[2] or 0))


def generated(value: object) -> object:
    """Expands `{repeat: {text: a, count: 1000000}}` into a string. It leaves any other value."""
    if isinstance(value, list):
        return [generated(one) for one in cast("list[object]", value)]
    if not isinstance(value, Mapping):
        return value
    found = cast("Json", value)
    if set(found) != {"repeat"}:
        return {key: generated(one) for key, one in found.items()}
    spec = mapping(found["repeat"])
    text, count = spec.get("text"), spec.get("count")
    if not (isinstance(text, str) and text and isinstance(count, int) and count > 0):
        raise ValueError(f"repeat needs a text and a count above 0, got {spec!r:.80}")
    if len(text) * count > MAX_GENERATED:
        raise ValueError(f"repeat gives more than {MAX_GENERATED} characters")
    return text * count


def mapping(value: object) -> Json:
    assert isinstance(value, Mapping), f"expected a mapping, got {value!r:.120}"
    return cast("Json", value)


def items(value: object) -> Sequence[object]:
    assert isinstance(value, list), f"expected a list, got {value!r:.120}"
    return cast("list[object]", value)


@functools.cache
def parsed(sidecar: Path, _modified: int) -> Json:
    return mapping(cast("object", yaml.safe_load(sidecar.read_text())))


def entries() -> Iterator[tuple[str, Json]]:
    for sidecar in sorted(FEATURES.glob("*.calls.yaml")):
        loaded = parsed(sidecar, sidecar.stat().st_mtime_ns)
        yield from ((scenario_id, mapping(entry)) for scenario_id, entry in loaded.items())


def runs() -> list[tuple[str, Json, Json]]:
    found: list[tuple[str, Json, Json]] = []
    for scenario_id, entry in entries():
        found += [(scenario_id, entry, {})] if "fixture" in entry else []
        variants = mapping(entry.get("variants", {})).items()
        found += [(f"{scenario_id}/{name}", entry, mapping(one)) for name, one in variants]
    return found


def select(value: object, path: str) -> object:
    if not path:
        return value
    token = _SELECTOR.match(path)
    assert token is not None, f"{path!r} is not a selector"
    index, field_name, field_value, name = token.groups()
    rest = path[token.end() :]
    if field_name is not None:
        hits = [one for one in items(value) if mapping(one).get(field_name) == field_value]
        assert hits, f"{path}: no item with {field_name} {field_value!r} in {value!r:.200}"
        return select(hits[0], rest)
    if index == "*":
        return [select(item, rest) for item in items(value)]
    if index is not None:
        return select(items(value)[int(index)], rest)
    found = mapping(value)
    assert name in found, f"{path}: no {name!r} in {value!r:.200}"
    return select(found[name], rest)


class _Markup(HTMLParser):
    def __init__(self, tag: str, name: str) -> None:
        super().__init__()
        self.tag: str = tag
        self.name: str = name
        self.found: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.found += [one for key, one in attrs if tag == self.tag and key == self.name and one]


def attribute_in(markup: object, query: str) -> str:
    wanted = _MARKUP.fullmatch(query)
    if wanted is None or not isinstance(markup, str):
        raise AssertionError(f"{query!r} is not tag[attribute] of text")
    parser = _Markup(*wanted.groups())
    parser.feed(markup)
    if not parser.found:
        raise AssertionError(f"no <{wanted[1]}> with {wanted[2]} in {markup!r:.200}")
    return parser.found[0]


def resolved(value: object, results: Sequence[object]) -> object:
    if isinstance(value, list):
        return [resolved(item, results) for item in cast("list[object]", value)]
    if isinstance(value, Mapping):
        found = cast("Json", value)
        if set(found) == {"repeat"}:
            return generated(found)
        return {key: resolved(one, results) for key, one in found.items()}
    if not isinstance(value, str):
        return value
    if value.startswith("$"):
        root, _, path = value[1:].partition(".")
        path, _, markup = path.partition("~")
        found = select(results[-1] if root == "prev" else results[int(root) - 1], path)
        return attribute_in(found, markup) if markup else found
    if value in _DAYS:
        return day_named(value).isoformat()
    return _SYMBOL.sub(lambda word: day_named(word[1]).isoformat(), value)


def _text(spec: object) -> object:
    if isinstance(spec, str) and _REFERENCE.fullmatch(spec):
        module, _, name = spec.rpartition(".")
        return cast("object", getattr(importlib.import_module(f"office_365_mcp.{module}"), name))
    if not isinstance(spec, Mapping):
        return spec
    ((function, arguments),) = cast("Json", spec).items()
    call = cast("Callable[..., object]", _text(function))
    if isinstance(arguments, Mapping):
        return call(**{key: _text(value) for key, value in cast("Json", arguments).items()})
    return call(*(_text(value) for value in items(arguments)))


def expected_error(spec: object) -> str:
    named = isinstance(spec, Mapping) or _REFERENCE.fullmatch(str(spec))
    text = _text(cast("object", spec)) if named else None
    assert isinstance(text, str), f"tool_error {spec!r} names no text constant of office_365_mcp"
    return text


def _utc_date(stamp: str) -> date:
    parsed = datetime.fromisoformat(stamp)
    return (parsed if parsed.tzinfo is None else parsed.astimezone(UTC)).date()


def same(expected: object, actual: object) -> bool:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        wanted, got = cast("Json", expected), cast("Json", actual)
        return wanted.keys() == got.keys() and all(same(wanted[k], got[k]) for k in wanted)
    if isinstance(expected, list) and isinstance(actual, list):
        wanted_items, got_items = cast("list[object]", expected), cast("list[object]", actual)
        return len(wanted_items) == len(got_items) and all(
            map(same, wanted_items, got_items, strict=True)
        )
    if not (isinstance(expected, str) and isinstance(actual, str)):
        return expected == actual
    if (sized := _SIZED.fullmatch(expected)) is not None:
        return len(actual) == int(sized[1])
    parts = _SYMBOL.split(expected)
    pattern = "".join(re.escape(p) if n % 2 == 0 else f"({_DATETIME})" for n, p in enumerate(parts))
    found = re.fullmatch(pattern, actual)
    return found is not None and all(
        abs((_utc_date(stamp) - day_named(word)).days) <= 1
        for word, stamp in zip(parts[1::2], found.groups(), strict=True)
    )


def _asked(request: httpx.Request) -> Json:
    try:
        body = cast("object", json.loads(request.content)) if request.content else None
    except ValueError:
        body = request.content.decode(errors="replace")
    headers = {name: request.headers[name] for name in _REQUEST_HEADERS if name in request.headers}
    query = dict(parse_qsl(request.url.query.decode(), keep_blank_values=True))
    where = {"method": request.method, "host": request.url.host, "path": unquote(request.url.path)}
    return where | {"query": query, "headers": headers, "json": body}


def _without_generated(body: object) -> object:
    if isinstance(body, Mapping):
        return {key: one for key, one in cast("Json", body).items() if key not in _GENERATED_KEYS}
    return body


def _same_headers(wanted: object, got: object) -> bool:
    def tokens(headers: object) -> dict[str, list[str]]:
        return {name: sorted(str(one).split(", ")) for name, one in mapping(headers).items()}

    return tokens(wanted) == tokens(got)


def _matches(interaction: Json, asked: Json) -> bool:
    return (
        interaction.get("method") == asked["method"]
        and same(interaction.get("path"), asked["path"])
        and interaction.get("host", "graph.microsoft.com") == asked["host"]
        and _same_headers(interaction.get("headers", {}), asked["headers"])
        and same(interaction.get("query", {}), asked["query"])
        and same(_without_generated(interaction.get("json")), _without_generated(asked["json"]))
    )


@dataclass
class Replay:
    interactions: Sequence[Json]
    step: int = 0
    fault: Json = field(default_factory=dict[str, object])
    faults_left: int = 0
    seen: set[int] = field(default_factory=set)
    served: set[int] = field(default_factory=set)
    reusable: set[int] = field(default_factory=set)
    calls: list[tuple[int, str]] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        call = f"{request.method} {unquote(request.url.path)}"
        self.calls.append((self.step, call))
        sent = cast("str | None", request.headers.get("authorization"))
        carries_token = sent == f"Bearer {_OBO_TOKEN}"
        if carries_token != (request.url.host == "graph.microsoft.com"):
            self.unmatched.append(f"{call} on {request.url.host}: the OBO token is {carries_token}")
            return httpx.Response(418)
        asked = _asked(request)
        open_ = [
            n for n in range(len(self.interactions)) if n not in self.served or n in self.reusable
        ]
        index = next((n for n in open_ if _matches(self.interactions[n], asked)), None)
        if index is None:
            waiting = [json.dumps(i) for n, i in enumerate(self.interactions) if n not in self.seen]
            self.unmatched.append(
                json.dumps({key: value for key, value in asked.items() if value})
                + "\n  no request reached these interactions yet:\n  "
                + ("\n  ".join(waiting) or "(none)")
            )
            return httpx.Response(418)
        self.seen.add(index)
        if self.faults_left and fnmatch(call, str(self.fault.get("at", "*"))):
            self.faults_left -= 1
            if "transport" in self.fault:
                raise httpx.ReadTimeout("injected by the sidecar fault", request=request)
            return response(mapping(self.fault["graph"]), HERE / "bodies")
        self.served.add(index)
        return response(self.interactions[index], HERE / "bodies")

    def counted(self, step: int, expected: Json) -> dict[str, int]:
        made = [call for at, call in self.calls if at == step]
        return dict(Counter(next((k for k in expected if fnmatch(c, k)), c) for c in made))


@dataclass
class Person:
    approval: object = None
    asked: list[str] = field(default_factory=list)

    async def __call__(
        self, message: str, _type: type | None, params: ElicitRequestParams, _context: object
    ) -> ElicitResult[dict[str, str]]:
        self.asked.append(message)
        if self.approval == "unanswered":
            raise RuntimeError("no answer arrived from the user")
        if self.approval in {"no", "silent"}:
            return ElicitResult(action="decline")
        assert isinstance(params, ElicitRequestFormParams)
        answers = mapping(mapping(cast("object", params.requested_schema["properties"]))["value"])
        return ElicitResult(action="accept", content={"value": str(items(answers["enum"])[0])})


def build_server() -> FastMCP[None]:
    entra = {"tenant_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81", "client_id": _CLIENT_ID}
    app = create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-365-mcp.example"}),
        database_config=DatabaseConfig.model_validate({"url": "postgresql://u:p@127.0.0.1:1/x"}),
        entra_config=EntraConfig.model_validate(entra | {"client_secret": "s3cr3t"}),
        surface_config=SurfaceConfig.model_validate({"tools_enabled": ",".join(TOOL_NAMES)}),
    )
    return cast("FastMCP[None]", app.state.fastmcp_server)


@pytest.fixture(scope="module")
def server() -> FastMCP[None]:
    return build_server()


class _Obo:
    async def get_token(self, *_scopes: str) -> GraphAccessToken:
        return GraphAccessToken(token=_OBO_TOKEN, expires_on=0)


def patch_obo(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exchange(_self: AzureProvider, *, user_assertion: str) -> _Obo:
        assert user_assertion == _CLIENT_TOKEN
        return _Obo()

    monkeypatch.setattr(AzureProvider, "get_obo_credential", exchange)
    monkeypatch.setattr(
        "fastmcp.server.dependencies.get_access_token",
        lambda: AccessToken(token=_CLIENT_TOKEN, client_id=_CLIENT_ID, scopes=["access_as_user"]),
    )


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_obo(monkeypatch)


async def run_chain(
    steps: Sequence[Json], fixture: str, server: FastMCP[None], retry_sleeps: RecordedSleeps
) -> Person:
    recorded = cast("object", json.loads((HERE / "fixtures" / f"{fixture}.json").read_text()))
    replay, person = Replay([mapping(one) for one in items(recorded)]), Person()
    results: list[object] = []
    with respx.mock(assert_all_mocked=True) as graph:
        _ = graph.route().mock(side_effect=replay)
        async with Client(FastMCPTransport(server), elicitation_handler=person, mode="legacy") as c:
            for number, step in enumerate(steps, 1):
                results.append(await _step(c, replay, person, retry_sleeps, number, step, results))
    unused = [json.dumps(one) for n, one in enumerate(replay.interactions) if n not in replay.seen]
    assert unused == [], f"fixture {fixture}: no request reached\n" + "\n".join(unused)
    return person


@pytest.mark.usefixtures("obo")
@pytest.mark.parametrize(("entry", "variant"), [r[1:] for r in runs()], ids=[r[0] for r in runs()])
async def test_the_scenario_runs_as_its_sidecar_says(
    entry: Json, variant: Json, server: FastMCP[None], retry_sleeps: RecordedSleeps
) -> None:
    overrides = cast("Mapping[object, object]", variant)
    steps = [
        {**mapping(step), **mapping(overrides.get(n, {}))}
        for n, step in enumerate(items(entry["chain"]), 1)
    ]
    person = await run_chain(
        steps, str(variant.get("fixture", entry.get("fixture"))), server, retry_sleeps
    )
    assert bool(person.asked) == entry["asks_user"], f"asks_user, but asked {person.asked}"


async def _step(
    client: Client[FastMCPTransport],
    replay: Replay,
    person: Person,
    sleeps: RecordedSleeps,
    number: int,
    step: Json,
    results: Sequence[object],
) -> object:
    tool = str(step.get("pick", step.get("tool")))
    fault, expect = mapping(step.get("fault", {})), mapping(step.get("expect", {}))
    given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
    given |= mapping(fault.get("input", {}))
    replay.step, replay.fault = number, fault
    faulty = {"graph", "transport"} & set(fault)
    replay.faults_left = cast("int", fault.get("times", 1)) if faulty else 0
    person.approval = step.get("approval")
    asked_before, slept = len(person.asked), len(sleeps.delays)
    where, error, outcome = f"step {number} ({tool})", None, None
    try:
        answer = await client.call_tool(tool, {k: resolved(v, results) for k, v in given.items()})
        outcome = answer.structured_content or {
            "content": [block.model_dump(mode="json", by_alias=True) for block in answer.content]
        }
    except ToolError as refused:
        error = str(refused)
    assert not replay.unmatched, f"{where}: no fixture interaction matches\n" + "\n".join(
        replay.unmatched
    )
    assert replay.faults_left == 0, f"{where}: {replay.faults_left} faults reached no request"
    asked = person.asked[asked_before:]
    if person.approval == "silent":
        assert not asked, f"{where}: approval is silent, and the user was asked {asked}"
    elif person.approval is not None:
        assert asked, f"{where}: approval is {person.approval}, and the user was never asked"
    if "tool_error" in expect:
        wanted = expected_error(expect["tool_error"])
        assert error is not None and wanted in error, f"{where}: no {wanted!r} in {error!r}"
    else:
        assert error is None, f"{where} failed: {error}"
    for path, value in mapping(expect.get("result", {})).items():
        assert select(outcome, path) == value, f"{where}: {path} is {select(outcome, path)!r}"
    if "graph_calls" in expect:
        made = replay.counted(number, mapping(expect["graph_calls"]))
        assert made == expect["graph_calls"], f"{where}: Graph calls {made}"
    if "retry_sleeps" in expect:
        assert sleeps.delays[slept:] == expect["retry_sleeps"], f"{where}: slept {sleeps.delays}"
    return outcome


def _ask(url: str, token: str | None) -> httpx.Request:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return httpx.Request("GET", url, headers=headers)


def test_a_redirect_answer_carries_its_own_headers() -> None:
    replay = Replay(
        [{"method": "GET", "host": "contoso.sharepoint.com", "path": "/f", "status": 200}]
    )
    moved = response(
        {
            "status": 302,
            "headers": {"authorization": "x"},
            "response_headers": {"location": "https://a/b"},
        }
    )
    assert moved.headers["location"] == "https://a/b"
    assert "authorization" not in moved.headers
    assert replay(_ask("https://contoso.sharepoint.com/f", None)).status_code == 200


def test_the_obo_token_goes_to_graph_only() -> None:
    replay = Replay([{"method": "GET", "path": "/v1.0/me", "status": 200}])
    assert replay(_ask("https://graph.microsoft.com/v1.0/me", None)).status_code == 418
    assert replay(_ask("https://other.example/v1.0/me", _OBO_TOKEN)).status_code == 418
    assert len(replay.unmatched) == 2


def test_the_number_of_executable_scenarios_only_goes_up() -> None:
    assert len(runs()) >= _MINIMUM_EXECUTABLE, (
        f"{len(runs())} runs, fewer than _MINIMUM_EXECUTABLE = {_MINIMUM_EXECUTABLE}. The number "
        + "only goes up: restore the run, or lower the constant in a change that says why."
    )


def _status(interaction: Json, method: str, path: str, body: object = None) -> int:
    headers = {"authorization": f"Bearer {_OBO_TOKEN}"}
    request = httpx.Request(
        method, f"https://graph.microsoft.com{path}", json=body, headers=headers
    )
    return Replay([interaction])(request).status_code


def test_a_transaction_id_at_the_top_of_a_body_never_decides_the_match() -> None:
    saved = {"transactionId": "00000000-1111-4222-8333-444444444444"}
    first = {"method": "POST", "path": "/v1.0/me/events", "status": 201}
    interaction = first | {"json": {"subject": "s"} | saved}
    derived = {"transactionId": "25d08be4-0986-5ceb-ac2a-fbd5a0e689f5"}
    assert _status(interaction, "POST", "/v1.0/me/events", {"subject": "s"} | derived) == 201
    assert _status(interaction, "POST", "/v1.0/me/events", {"subject": "t"} | derived) == 418
    nested = first | {"json": {"event": saved}}
    assert _status(nested, "POST", "/v1.0/me/events", {"event": saved}) == 201
    assert _status(nested, "POST", "/v1.0/me/events", {"event": derived}) == 418


def test_an_external_id_at_the_top_of_a_body_never_decides_the_match() -> None:
    saved = {"externalId": "00000000-1111-4222-8333-444444444444"}
    first = {"method": "POST", "path": "/v1.0/me/onlineMeetings/createOrGet", "status": 200}
    interaction = first | {"json": {"subject": "s"} | saved}
    derived = {"externalId": "25d08be4-0986-5ceb-ac2a-fbd5a0e689f5"}
    path = "/v1.0/me/onlineMeetings/createOrGet"
    assert _status(interaction, "POST", path, {"subject": "s"} | derived) == 200
    assert _status(interaction, "POST", path, {"subject": "t"} | derived) == 418
    nested = first | {"json": {"meeting": saved}}
    assert _status(nested, "POST", path, {"meeting": derived}) == 418


def test_a_path_with_a_day_symbol_matches_on_another_day_and_other_paths_match_exactly() -> None:
    def window(first: date | str, last: date | str) -> str:
        stamp = "T00:00:00.0000000"
        return f"/v1.0/me/reminderView(startDateTime='{first}{stamp}',endDateTime='{last}{stamp}')"

    saved = window("~yesterday", "~tomorrow")
    interaction = {"method": "GET", "path": saved, "status": 200}
    assert _status(interaction, "GET", window(_DAYS["yesterday"], _DAYS["tomorrow"])) == 200
    assert _status(interaction, "GET", window(_DAYS["today"], _DAYS["tomorrow"])) == 200
    far = _TODAY + timedelta(5)
    assert _status(interaction, "GET", window(far, far)) == 418
    fixed = {"method": "GET", "path": "/v1.0/me/outlook/supportedTimeZones()", "status": 200}
    assert _status(fixed, "GET", "/v1.0/me/outlook/supportedTimeZones()") == 200
    assert _status(fixed, "GET", "/v1.0/me/outlook/supportedTimeZones") == 418


def test_a_selector_picks_an_item_by_the_value_of_a_field() -> None:
    answer = {"teams": [{"name": "a", "id": "1"}, {"name": "seed-v1 team", "id": "2"}]}
    assert select(answer, "teams[name=seed-v1 team].id") == "2"
    with pytest.raises((AssertionError, IndexError)):
        _ = select(answer, "teams[name=other].id")


def test_a_bind_reads_an_attribute_of_the_markup_a_step_returned() -> None:
    answer = {"html": '<html><body><p src="no">x</p><img alt="a" src="https://g/x"/></body></html>'}
    assert resolved("$prev.html~img[src]", [answer]) == "https://g/x"
    assert resolved("$1.html~img[alt]", [answer]) == "a"
    with pytest.raises(AssertionError, match="no <object> with data"):
        _ = resolved("$prev.html~object[data]", [answer])
    with pytest.raises(AssertionError, match="is not tag"):
        _ = resolved("$prev.html~img", [answer])


def test_a_bind_builds_a_person_object_from_earlier_answers() -> None:
    answer = {"people": [{"id": "1", "name": "Anna"}]}
    spec = {"user_id": "$prev.people[0].id", "name": "$prev.people[0].name"}
    assert resolved([spec], [answer]) == [{"user_id": "1", "name": "Anna"}]
    assert resolved({"x": ["plain", "$prev.people[0].id"]}, [answer]) == {"x": ["plain", "1"]}
