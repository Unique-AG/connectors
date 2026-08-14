import pytest


class TestCapstoneCustomFieldSpike:
    @pytest.mark.skip(
        reason=(
            "Manual spike: confirm Capstone Investor Status/Grade are custom fields "
            "via GET /custom-field-definitions (UN-23677); not runnable in CI"
        )
    )
    def test_capstone_investor_status_and_grade_are_custom_fields(self) -> None:
        """Manual: against Capstone test credentials, list custom-field-definitions and
        confirm whether Investor Status / Grade exist as custom fields (vs built-ins like
        categories / clientDefinedEntityType). Document outcome in the design note.
        """
        raise NotImplementedError("Run manually against Capstone test instance")
