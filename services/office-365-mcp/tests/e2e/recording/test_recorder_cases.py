import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from starlette.responses import JSONResponse

from office_365_mcp.tools import TOOL_NAMES
from tests.e2e.recording import guard as guard_module
from tests.e2e.recording import stand_in
from tests.e2e.recording.cases import case_entries
from tests.e2e.recording.conftest import record_on
from tests.e2e.recording.families import Merged, load, merge
from tests.e2e.recording.guard import SEED_CASE, WRITE_TOOLS, Guard, foreign_address, match_glob
from tests.e2e.recording.record import guard_for, main, resolve, tool_of
from tests.e2e.recording.stand_in import UPN
from tests.e2e.recording.stand_in import UPNS as STAND_IN_UPNS
from tests.e2e.test_scenarios import Json

GRAPH = "https://graph.microsoft.com/v1.0"
LIST_CASE = "outlook_list_mail-inbox"
MOVE_CASE = "outlook_move_mail-archive"


def family(**attributes: object) -> ModuleType:
    module = ModuleType("synthetic")
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


def guard(**fields: object) -> Guard:
    return Guard(UPN, frozenset({UPN}), True, **fields)  # pyright: ignore[reportArgumentType]


def request(method: str, path: str, body: str = "") -> httpx.Request:
    return httpx.Request(method, f"{GRAPH}{path}", content=body)


def patched(monkeypatch: pytest.MonkeyPatch, **fields: object) -> Merged:
    changed = replace(load(), **fields)
    monkeypatch.setattr(guard_module, "FAMILIES", changed)
    return changed


class TestFamilyLoading:
    def test_the_families_keep_the_old_allowlist(self) -> None:
        merged = load()
        assert {"outlook_list_mail", "outlook_list_events", "sharepoint_read_file"} <= (
            merged.read_tools
        )
        assert {
            "outlook_move_mail",
            "outlook_mark_mail",
            "outlook_draft_mail",
            "outlook_create_event",
        } <= set(merged.write_tools)
        assert merged.read_posts["sharepoint_search_files"] == ("POST /v1.0/search/query",)
        assert (merged.read_tools | set(merged.write_tools)) <= set(TOOL_NAMES)

    def test_every_tool_has_a_case_or_a_reason(self) -> None:
        merged = load()
        cased = {tool_of(resolve(case).steps[-1]) for case, _ in case_entries()}
        unrecorded = set(merged.unrecorded)
        assert cased | unrecorded == set(TOOL_NAMES)
        assert not cased & unrecorded
        assert not unrecorded & (merged.read_tools | set(merged.write_tools))
        assert all(merged.unrecorded.values())

    @pytest.mark.parametrize(
        ("modules", "message"),
        [
            (
                [family(READ_TOOLS=frozenset({"a"})), family(READ_TOOLS=frozenset({"a"}))],
                "claimed twice",
            ),
            (
                [family(READ_TOOLS=frozenset({"a"}), WRITE_TOOLS={"a": ("POST /v1.0/me/x",)})],
                "claimed twice",
            ),
            ([family(WRITE_TOOLS={"a": ("POST /v1.0/*/x",)})], "literal first segment"),
            ([family(WRITE_TOOLS={"a": ("POST /v1.0/me/**",)})], "literal first segment"),
            ([family(WRITE_TOOLS={"a": ("POST /v2/me/x",)})], "literal first segment"),
            ([family(READ_POSTS={"a": ("GET /v1.0/me/x",)})], "literal first segment"),
            ([family(READ_GETS={"a": ("POST /v1.0/me/x",)})], "literal first segment"),
            ([family(READ_GETS={"a": ("GET /v1.0/*/x",)})], "literal first segment"),
            ([family(READ_GETS={"a": ("GET /v1.0/me/**",)})], "literal first segment"),
            ([family(PREFIXES=("/v1.0/teams",))], "end in a slash"),
            ([family(THREAD_ID=(re.compile(r".*@thread.*"),))], "THREAD_ID"),
            ([family(THREAD_ID=(re.compile(r"[a-z]+"),))], "THREAD_ID"),
            ([family(SCHEMA={"a": "id"}), family(SCHEMA={"a": "text"})], "claimed twice"),
            ([family(NEEDS={"a": "x"}), family(NEEDS={"a": "y"})], "claimed twice"),
        ],
    )
    def test_a_bad_family_stops_the_import(self, modules: list[ModuleType], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            _ = merge(modules)

    def test_a_bad_family_stops_the_import_under_python_dash_o(self) -> None:
        code = (
            "from types import ModuleType\n"
            "from tests.e2e.recording.families import merge\n"
            "m = ModuleType('m'); m.READ_TOOLS = frozenset({'a'})\n"
            "try:\n    merge([m, m])\nexcept ValueError as e:\n    print('refused', e)\n"
        )
        done = subprocess.run(
            [sys.executable, "-O", "-c", code], capture_output=True, text=True, check=False
        )
        assert done.stdout.startswith("refused"), done.stderr

    def test_a_good_family_merges(self) -> None:
        thread = re.compile(r"[\w-]+@thread\.(?:tacv2|v2)")
        merged = merge(
            [
                family(READ_TOOLS=frozenset({"a"}), NEEDS={"k": "Do this."}),
                family(
                    WRITE_TOOLS={"b": ("POST /v1.0/teams",)},
                    EXTERNAL=frozenset({"b"}),
                    THREAD_ID=(thread,),
                    PROBES={"k": (2, "/me/joinedTeams", 1)},
                ),
            ]
        )
        assert merged.read_tools == {"a"}
        assert merged.external == {"b"}
        assert merged.thread_id == (thread,)
        assert merged.probes == {"k": (2, "/me/joinedTeams", 1)}

    def test_a_family_gap_covers_every_tool_that_the_family_claims(self) -> None:
        merged = merge(
            [
                family(READ_TOOLS=frozenset({"a"}), WRITE_TOOLS={"b": ()}, GAP_SECONDS=20),
                family(READ_TOOLS=frozenset({"c"})),
            ]
        )
        assert merged.gaps == {"a": 20, "b": 20}


class TestGuardPlugIns:
    def test_a_star_never_crosses_a_slash(self) -> None:
        assert match_glob("PATCH /v1.0/me/messages/*", "PATCH /v1.0/me/messages/a/b/c") is None
        assert match_glob("PATCH /v1.0/me/messages/*", "PATCH /v1.0/me/messages/a") == ["a"]
        assert match_glob("POST /v1.0/me/messages/*/move", "POST /v1.0/me/messages/a/move") == ["a"]

    def test_a_star_at_the_start_of_a_segment_gives_the_rest_of_the_segment_away(self) -> None:
        glob = "PUT /v1.0/drives/b!*/items/*:/seed-v1?case-*:/content"
        shown = "PUT /v1.0/drives/b!d/items/P1:/seed-v1 case-x.txt:/content"
        assert match_glob(glob, shown) == ["P1"]
        assert match_glob(glob, shown.replace("seed-v1 case", "other case")) is None
        assert match_glob(glob, shown.replace("P1:/", "P1/")) is None
        assert match_glob(glob, shown.replace("/content", "/children")) is None
        assert match_glob("GET /v1.0/me/a*", "GET /v1.0/me/abc") == []

    def test_a_write_to_a_nested_path_is_refused(self) -> None:
        made = guard(seen_seed={"a", "b"})
        refusal = made.refuses_request(request("PATCH", "/me/messages/a/b"), "outlook_mark_mail")
        assert refusal is not None
        assert "not a write path" in refusal

    def test_a_created_item_is_a_target_and_a_search_answer_is_not(self) -> None:
        made = guard(seen_seed=set[str]())
        create = request("POST", "/me/messages", '{"subject": "x"}')
        assert made.refuses_request(create, "outlook_draft_mail") is None
        made.saw(create, 201, None, {"id": "AAMkNEW"})
        search = request("POST", "/search/query")
        made.saw(search, 200, None, {"id": "AAMkFOREIGN"})
        assert made.created == {"AAMkNEW"}
        mark = made.refuses_request(request("PATCH", "/me/messages/AAMkNEW"), "outlook_mark_mail")
        foreign = made.refuses_request(
            request("PATCH", "/me/messages/AAMkFOREIGN"), "outlook_mark_mail"
        )
        assert mark is None
        assert foreign is not None
        assert "did not read as seed data" in foreign

    def test_a_write_outside_me_needs_its_glob_and_a_case_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(WRITE_TOOLS, "teams_x", ("POST /v1.0/teams", "PATCH /v1.0/chats/*"))
        made = guard()
        plain = made.refuses_request(request("POST", "/teams", '{"displayName": "x"}'), "teams_x")
        tagged = request("POST", "/teams", f'{{"displayName": "{SEED_CASE}teams_x-basic"}}')
        other = made.refuses_request(request("POST", "/teams", "{}"), "teams_y")
        patch = request("PATCH", "/chats/c1", "{}")
        assert plain is not None
        assert SEED_CASE in plain
        assert made.refuses_request(tagged, "teams_x") is None
        assert other is not None
        assert "outside /v1.0/me/" in other
        assert "did not read as seed data" in str(made.refuses_request(patch, "teams_x"))
        made.created.add("c1")
        assert made.refuses_request(patch, "teams_x") is None

    def test_a_forbidden_value_and_an_unknown_destination_are_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patched(
            monkeypatch,
            forbidden={"scope": frozenset({"anonymous"})},
            destinations=frozenset({"parentReference.id"}),
        )
        monkeypatch.setitem(WRITE_TOOLS, "link_x", ("POST /v1.0/me/drive/items/*/createLink",))
        made = guard(created={"i1"})
        link = request("POST", "/me/drive/items/i1/createLink", '{"scope": "anonymous"}')
        move = request("POST", "/me/drive/items/i1/createLink", '{"parentReference": {"id": "z"}}')
        assert "no recording may do" in str(made.refuses_request(link, "link_x"))
        assert "did not read as seed data" in str(made.refuses_request(move, "link_x"))

    def test_a_thread_id_is_not_an_address_but_an_unknown_at_still_is(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patched(monkeypatch, thread_id=(re.compile(r"[\w-]+@thread\.(?:tacv2|v2)"),))
        allowed = frozenset({UPN})
        assert foreign_address("19:abc-1@thread.tacv2", allowed) is None
        assert foreign_address("abc@thread.evil.com", allowed) is not None
        assert foreign_address("abc@evil.com", allowed) is not None

    def test_a_prefix_widens_get_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patched(monkeypatch, prefixes=("/v1.0/teams/",))
        made = guard()
        assert made.refuses_request(request("GET", "/teams/t1/channels"), "teams_x") is None
        assert made.refuses_request(request("POST", "/teams/t1/channels"), "teams_x") is not None
        assert made.refuses_request(request("GET", "/chats/c1"), "teams_x") is not None


class TestCases:
    def test_the_example_cases_parse_and_resolve(self) -> None:
        listing, move = resolve(LIST_CASE), resolve(MOVE_CASE)
        assert (listing.fixture, listing.case, listing.persona) == (
            f"rec-tool-{LIST_CASE}",
            True,
            1,
        )
        assert (move.destructive, move.reseed, move.cap) == (True, ("mail",), 0)

    def test_a_case_id_is_its_last_tool_and_a_slug(self) -> None:
        for case_id, entry in case_entries():
            last = str(entry["chain"][-1]["tool"])  # pyright: ignore[reportIndexIssue, reportUnknownArgumentType]
            assert case_id.startswith(f"{last}-"), case_id
            assert last in TOOL_NAMES

    def test_a_duplicate_case_id_raises(self, tmp_path: Path) -> None:
        for name in ("a.yaml", "b.yaml"):
            _ = (tmp_path / name).write_text("t-x:\n  chain: []\n")
        with pytest.raises(ValueError, match="defined twice"):
            _ = list(case_entries(tmp_path))

    def test_a_case_carries_its_options(self, tmp_path: Path) -> None:
        _ = (tmp_path / "f.yaml").write_text(
            "outlook_list_mail-x:\n  persona: 2\n  cap: 7\n  external: true\n  needs: [k]\n"
            + "  chain:\n    - {tool: outlook_list_mail}\n"
        )
        plan = resolve("outlook_list_mail-x", cases=tmp_path)
        assert (plan.persona, plan.cap, plan.external, plan.needs) == (2, 7, True, ("k",))
        assert guard_for(STAND_IN_UPNS, plan, False, 40).allowed_upn == STAND_IN_UPNS[1]
        assert guard_for(STAND_IN_UPNS, plan, False, 40).cap == 7

    @pytest.mark.parametrize(("option", "value"), [("persona", 4), ("persona", 0), ("cap", 101)])
    def test_a_persona_or_cap_out_of_range_is_refused(
        self, tmp_path: Path, option: str, value: int
    ) -> None:
        _ = (tmp_path / "f.yaml").write_text(
            f"outlook_list_mail-x:\n  {option}: {value}\n"
            + "  chain:\n    - {tool: outlook_list_mail}\n"
        )
        plan = resolve("outlook_list_mail-x", cases=tmp_path)
        with pytest.raises(guard_module.Refused):
            _ = guard_for(STAND_IN_UPNS, plan, False, 40)

    def test_a_case_records_against_the_stand_in_and_replays(self) -> None:
        listing = record_on(LIST_CASE)
        move = record_on(MOVE_CASE)
        assert listing.fixture.name == f"rec-tool-{LIST_CASE}"
        assert move.fixture.name == f"rec-tool-{MOVE_CASE}"
        assert listing.unmet == move.unmet == []
        assert "@odata.context" in listing.fixture.dropped
        assert any("dropped: @odata.context" in line for line in listing.report)

    def test_a_persona_that_is_not_the_token_user_is_refused(self, tmp_path: Path) -> None:
        _ = (tmp_path / "f.yaml").write_text(
            "outlook_list_mail-x:\n  persona: 2\n  chain:\n    - {tool: outlook_list_mail}\n"
        )
        with pytest.raises(guard_module.Refused, match="SEED_UPNS position 2"):
            _ = record_on(resolve("outlook_list_mail-x", cases=tmp_path))

    def test_a_transient_refusal_names_retry_after(self) -> None:
        with pytest.raises(guard_module.Refused, match=r"retry-after \d+"):
            _ = record_on("uc-02-01", stand_in.StandIn(frozenset({"retry"})))

    def test_a_transient_answer_with_no_header_still_names_retry_after(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = stand_in._error  # pyright: ignore[reportPrivateUsage]

        def bare(status: int, code: str, message: str, *_: object) -> JSONResponse:
            return original(status, code, message)

        monkeypatch.setattr(stand_in, "_error", bare)
        with pytest.raises(guard_module.Refused, match=r"retry-after 0$"):
            _ = record_on("uc-02-01", stand_in.StandIn(frozenset({"retry"})))

    def test_a_case_names_extra_scopes_and_a_gap(self, tmp_path: Path) -> None:
        _ = (tmp_path / "f.yaml").write_text(
            "outlook_list_mail-x:\n  scopes: [Group.Read.All]\n  gap: 9\n"
            + "  chain:\n    - {tool: outlook_list_mail}\n"
        )
        plan = resolve("outlook_list_mail-x", cases=tmp_path)
        assert (plan.scopes, plan.gap) == (("Group.Read.All",), 9)

    @pytest.mark.parametrize(
        ("option", "value"),
        [("scopes", "[https://x.test/y]"), ("scopes", "[Group]"), ("gap", -1), ("gap", 601)],
    )
    def test_a_scope_that_is_no_permission_name_or_a_long_gap_is_refused(
        self, tmp_path: Path, option: str, value: object
    ) -> None:
        _ = (tmp_path / "f.yaml").write_text(
            f"outlook_list_mail-x:\n  {option}: {value}\n"
            + "  chain:\n    - {tool: outlook_list_mail}\n"
        )
        with pytest.raises(guard_module.Refused):
            _ = resolve("outlook_list_mail-x", cases=tmp_path)

    def test_link_with_a_case_is_refused_before_any_request(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("SEED_UPNS", ",".join(STAND_IN_UPNS))
        assert main([LIST_CASE, "--target", "graph", "--link"]) == 2
        assert "--link does not apply to a tool case" in capsys.readouterr().err

    def test_the_cli_dry_run_of_the_cases_sends_nothing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main([LIST_CASE, MOVE_CASE, "--target", "stand-in", "--dry-run", "--allow-writes"])
        out = capsys.readouterr().out
        assert code == 0
        assert out.count("allowed") == 3


def test_the_scrub_keeps_a_json_plan_literal() -> None:
    steps: tuple[Json, ...] = resolve(MOVE_CASE).steps
    assert steps[1]["args"] == {"destination": "archive"}
