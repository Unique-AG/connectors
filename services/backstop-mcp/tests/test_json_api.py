import pytest
from pydantic import BaseModel, ValidationError

from backstop_mcp.backstop_client.json_api import (
    BackstopApiCollectionDocument,
    BackstopApiResource,
    BackstopApiResourceDocument,
    ResourceRef,
    follow_included,
)


class _Attrs(BaseModel):
    name: str


# Backstop's inline reference format, field for field as the live instance sends it: this is
# `opportunity-stage-history.attributes.stage` as it actually arrives.
_STAGE_REF = {
    "resourceType": "opportunity-stages",
    "resourceId": "42482",
    "resourceLink": "https://fb-rm-lg-26.backstopsolutions.com/backstop/api/opportunity-stages/42482",
    "restricted": False,
}


class TestBackstopApiResourceDocument:
    def test_validates_typed_attributes(self) -> None:
        doc = BackstopApiResourceDocument[_Attrs].model_validate(
            {"data": {"id": "1", "type": "party", "attributes": {"name": "Acme"}}}
        )

        assert isinstance(doc.data, BackstopApiResource)
        assert doc.data.id == "1"
        assert doc.data.type == "party"
        assert isinstance(doc.data.attributes, _Attrs)
        assert doc.data.attributes.name == "Acme"

    def test_rejects_null_data(self) -> None:
        with pytest.raises(ValidationError):
            BackstopApiResourceDocument[_Attrs].model_validate({"data": None})

    def test_rejects_a_collection(self) -> None:
        with pytest.raises(ValidationError):
            BackstopApiResourceDocument[_Attrs].model_validate(
                {
                    "data": [
                        {"id": "1", "type": "party", "attributes": {"name": "Acme"}},
                    ]
                }
            )

    def test_preserves_included_side_loads(self) -> None:
        doc = BackstopApiResourceDocument[_Attrs].model_validate(
            {
                "data": {
                    "id": "1",
                    "type": "people",
                    "attributes": {"name": "Jane"},
                    "relationships": {
                        "entityRelationships": {
                            "data": [{"type": "entity-relationships", "id": "er1"}]
                        }
                    },
                },
                "included": [
                    {
                        "type": "entity-relationships",
                        "id": "er1",
                        "attributes": {"endDate": "2020-01-01"},
                    }
                ],
            }
        )

        assert len(doc.included) == 1
        assert doc.included[0]["id"] == "er1"


class TestBackstopApiCollectionDocument:
    def test_validates_list_of_typed_resources(self) -> None:
        doc = BackstopApiCollectionDocument[_Attrs].model_validate(
            {
                "data": [
                    {"id": "1", "type": "party", "attributes": {"name": "Acme"}},
                    {"id": "2", "type": "party", "attributes": {"name": "Globex"}},
                ]
            }
        )

        assert [item.attributes.name for item in doc.data] == ["Acme", "Globex"]

    def test_rejects_a_single_resource(self) -> None:
        with pytest.raises(ValidationError):
            BackstopApiCollectionDocument[_Attrs].model_validate(
                {"data": {"id": "1", "type": "party", "attributes": {"name": "Acme"}}}
            )

    def test_rejects_null_data(self) -> None:
        with pytest.raises(ValidationError):
            BackstopApiCollectionDocument[_Attrs].model_validate({"data": None})


class TestFollowIncluded:
    def test_resolves_side_loaded_resources_in_linkage_order(self) -> None:
        document = BackstopApiResourceDocument[_Attrs].model_validate(
            {
                "data": {
                    "id": "1",
                    "type": "people",
                    "attributes": {"name": "Jane"},
                    "relationships": {
                        "entityRelationships": {
                            "data": [
                                {"type": "entity-relationships", "id": "er2"},
                                {"type": "entity-relationships", "id": "er1"},
                            ]
                        }
                    },
                },
                "included": [
                    {"type": "entity-relationships", "id": "er1", "attributes": {}},
                    {"type": "entity-relationships", "id": "er2", "attributes": {}},
                ],
            }
        )
        related = follow_included(document.included, document.data, "entityRelationships")

        assert [item["id"] for item in related] == ["er2", "er1"]

    def test_matches_by_type_and_id_when_ids_collide_across_types(self) -> None:
        """Backstop reuses numeric ids across resource types in one `included` array."""
        document = BackstopApiResourceDocument[_Attrs].model_validate(
            {
                "data": {
                    "id": "1",
                    "type": "people",
                    "attributes": {"name": "Jane"},
                    "relationships": {
                        "entityRelationships": {
                            "data": [{"type": "entity-relationships", "id": "42"}]
                        }
                    },
                },
                "included": [
                    {
                        "type": "entity-relationship-types",
                        "id": "42",
                        "attributes": {"name": "Employment"},
                    },
                    {
                        "type": "entity-relationships",
                        "id": "42",
                        "attributes": {"endDate": "2020-01-01"},
                    },
                ],
            }
        )
        related = follow_included(document.included, document.data, "entityRelationships")

        assert len(related) == 1
        assert related[0]["type"] == "entity-relationships"
        assert related[0]["attributes"] == {"endDate": "2020-01-01"}


class TestBackstopApiResourceIdValidation:
    def test_id_is_stripped(self) -> None:
        resource = BackstopApiResource[_Attrs].model_validate(
            {"id": "  1  ", "type": "party", "attributes": {"name": "Acme"}}
        )

        assert resource.id == "1"

    def test_blank_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BackstopApiResource[_Attrs].model_validate(
                {"id": "   ", "type": "party", "attributes": {"name": "Acme"}}
            )

    def test_type_is_stripped_but_blank_type_is_allowed(self) -> None:
        resource = BackstopApiResource[_Attrs].model_validate(
            {"id": "1", "type": "  ", "attributes": {"name": "Acme"}}
        )

        assert resource.type == ""


class TestResourceRef:
    """Backstop's second reference format — inline in an attribute, not JSON:API linkage."""

    def test_reads_the_three_fields_backstop_spells_in_camel_case(self) -> None:
        reference = ResourceRef.model_validate(_STAGE_REF)

        assert reference.model_dump() == {
            "resource_id": "42482",
            "resource_type": "opportunity-stages",
            "resource_link": (
                "https://fb-rm-lg-26.backstopsolutions.com/backstop/api/opportunity-stages/42482"
            ),
        }

    def test_an_attribute_we_do_not_model_is_dropped(self) -> None:
        assert "restricted" not in ResourceRef.model_validate(_STAGE_REF).model_dump()

    def test_the_type_and_the_link_are_optional(self) -> None:
        reference = ResourceRef.model_validate({"resourceId": "42482"})

        assert (reference.resource_type, reference.resource_link) == (None, None)

    def test_a_reference_with_no_id_is_rejected(self) -> None:
        """A reference nobody can resolve is not a reference."""
        with pytest.raises(ValidationError):
            ResourceRef.model_validate({key: _STAGE_REF[key] for key in ("resourceType",)})

    def test_a_blank_id_is_rejected_like_a_missing_one(self) -> None:
        with pytest.raises(ValidationError):
            ResourceRef.model_validate({**_STAGE_REF, "resourceId": "  "})
