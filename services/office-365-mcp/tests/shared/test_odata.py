from enum import Enum

import pytest
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.online_meeting_provider_type import OnlineMeetingProviderType

from office_365_mcp.shared.odata import spelled


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
