import pathlib
from enum import Enum

import pytest
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.online_meeting_provider_type import OnlineMeetingProviderType

from office_365_mcp.shared.odata import spelled

_SRC = pathlib.Path(__file__).parent.parent.parent / "src" / "office_365_mcp"
_OWNER = _SRC / "shared" / "odata.py"
_SPELLING = "str.__str__("
_GUARDED = sorted(
    source
    for folder in (_SRC / "tools", _SRC / "shared")
    for source in folder.rglob("*.py")
    if source != _OWNER
)


def _source_id(source: pathlib.Path) -> str:
    return str(source.relative_to(_SRC))


class TestSpelled:
    @pytest.mark.parametrize(
        ("member", "wire"),
        [
            (Importance.High, "high"),
            (FollowupFlagStatus.NotFlagged, "notFlagged"),
            (OnlineMeetingProviderType.TeamsForBusiness, "teamsForBusiness"),
        ],
    )
    def test_an_enum_member_is_the_value_graph_sends_for_it(self, member: Enum, wire: str) -> None:
        assert isinstance(member, str)
        assert spelled(member) == wire
        assert str(member) != wire

    def test_none_stays_none(self) -> None:
        assert spelled(None) is None


class TestOnlyTheOwnerSpellsAnEnum:
    def test_the_owner_actually_spells_it(self) -> None:
        assert _SPELLING in _OWNER.read_text()

    def test_the_guard_reads_both_folders(self) -> None:
        assert {source.parent.name for source in _GUARDED} == {"tools", "shared"}

    @pytest.mark.parametrize("source", _GUARDED, ids=_source_id)
    def test_no_other_module_spells_it(self, source: pathlib.Path) -> None:
        assert _SPELLING not in source.read_text(), (
            f"{_source_id(source)} spells a Graph enum with str.__str__. "
            + "Use spelled() from shared/odata.py."
        )
