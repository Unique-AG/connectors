"""Runs the chain of each recorder case through the real app, middleware and tools, with Graph
answered by the recording of that case. The run happens on the day of the recording, because a
day symbol of a recording matches the day of the run within one day. A case does not run when
its recording does not hold the chain that the case states now."""

from datetime import UTC, datetime, tzinfo
from typing import Self, cast, override

import pytest
import yaml
from fastmcp import FastMCP

from office_365_mcp.tools import onenote_create_page
from tests.conftest import RecordedSleeps
from tests.e2e import test_scenarios
from tests.e2e.recording import stand_in
from tests.e2e.recording.cases import case_entries
from tests.e2e.recording.record import persona_values, with_personas
from tests.e2e.test_scenarios import HERE, build_server, items, mapping, patch_obo, run_chain

_IDS = {
    "anna": "00000000-a6b4-4b6e-8a2b-9e1c3f1e88e1",
    "tom": "00000000-e469-40d3-8f5b-9a7c5dac541e",
}
_PERSONAS = persona_values(stand_in.UPNS, {}, synthetic=True) | {
    f"persona:{key}.id": one for key, one in _IDS.items()
}
_NEEDS_RE_RECORDING = frozenset(
    {
        "onenote_get_operation-notebook",
        "onenote_list_pages-team",
        "outlook_list_group_events-team",
        "outlook_respond_to_invite-accept",
        "outlook_send_draft-persona",
        "outlook_share_calendar-anna",
        "outlook_unshare_calendar-anna",
        "teams_browse_channel-long",
        "teams_list_channels-private",
    }
)
_RUNNABLE = {
    case: entry
    for case, entry in case_entries()
    if case not in _NEEDS_RE_RECORDING and (HERE / "fixtures" / f"rec-tool-{case}.json").is_file()
}


@pytest.fixture(scope="module")
def server() -> FastMCP[None]:
    return build_server()


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_obo(monkeypatch)


def _freeze_the_clock(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    class Frozen(datetime):
        @classmethod
        @override
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cast("Self", moment.astimezone(tz))

    monkeypatch.setattr(test_scenarios, "_TODAY", moment.date())
    monkeypatch.setattr(onenote_create_page, "datetime", Frozen)


@pytest.mark.usefixtures("obo")
@pytest.mark.parametrize("case", _RUNNABLE)
async def test_the_case_runs_against_its_recording(
    case: str, server: FastMCP[None], retry_sleeps: RecordedSleeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = (HERE / "fixtures" / f"rec-tool-{case}.meta.yaml").read_text()
    meta = mapping(cast("object", yaml.safe_load(stored)))
    _freeze_the_clock(monkeypatch, datetime.fromisoformat(str(meta["recorded_at"])).astimezone(UTC))
    steps = [mapping(with_personas(step, _PERSONAS)) for step in items(_RUNNABLE[case]["chain"])]
    _ = await run_chain(steps, f"rec-tool-{case}", server, retry_sleeps)
