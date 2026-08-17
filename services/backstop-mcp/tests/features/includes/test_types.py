"""Backstop's inline reference format.

The `ResourceRef` payload is the live instance's, field for field: it is
`opportunity-stage-history.attributes.stage` as it actually arrives.
"""

import pytest
from pydantic import ValidationError

from backstop_mcp.features.includes import ResourceRef

_STAGE = {
    "resourceType": "opportunity-stages",
    "resourceId": "42482",
    "resourceLink": "https://fb-rm-lg-26.backstopsolutions.com/backstop/api/opportunity-stages/42482",
    "restricted": False,
}


class TestResourceRef:
    def test_reads_the_three_fields_backstop_spells_in_camel_case(self) -> None:
        reference = ResourceRef.model_validate(_STAGE)

        assert reference.model_dump() == {
            "resource_id": "42482",
            "resource_type": "opportunity-stages",
            "resource_link": (
                "https://fb-rm-lg-26.backstopsolutions.com/backstop/api/opportunity-stages/42482"
            ),
        }

    def test_an_attribute_we_do_not_model_is_dropped(self) -> None:
        assert "restricted" not in ResourceRef.model_validate(_STAGE).model_dump()

    def test_the_type_and_the_link_are_optional(self) -> None:
        reference = ResourceRef.model_validate({"resourceId": "42482"})

        assert (reference.resource_type, reference.resource_link) == (None, None)

    def test_a_reference_with_no_id_is_rejected(self) -> None:
        """A reference nobody can resolve is not a reference."""
        with pytest.raises(ValidationError):
            ResourceRef.model_validate({key: _STAGE[key] for key in ("resourceType",)})

    def test_a_blank_id_is_rejected_like_a_missing_one(self) -> None:
        with pytest.raises(ValidationError):
            ResourceRef.model_validate({**_STAGE, "resourceId": "  "})
