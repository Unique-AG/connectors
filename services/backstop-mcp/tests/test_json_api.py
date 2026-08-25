import pytest
from pydantic import BaseModel, ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiCollectionDocument,
    BackstopApiError,
    BackstopApiResource,
    BackstopApiResourceDocument,
    IncludedResource,
    ResourceRef,
    follow_included,
    included_resource,
)


class _Attrs(BaseModel):
    name: str


class _OptionalAttrs(BaseModel):
    name: str | None = None


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

    def test_accepts_null_data_so_a_missing_record_is_not_a_schema_error(self) -> None:
        """`/entity-activity-details/{unknown}` answers `200 {"data": null}` rather than 404.

        Modelling `data` as required turned that into a `BackstopResponseSchemaError` reading
        like a broken schema instead of a missing record.
        """
        doc = BackstopApiResourceDocument[_Attrs].model_validate({"data": None})

        assert doc.data is None

    def test_require_data_turns_null_primary_data_into_a_404(self) -> None:
        doc = BackstopApiResourceDocument[_Attrs].model_validate({"data": None})

        with pytest.raises(BackstopApiError) as exc_info:
            doc.require_data(path="/entity-activity-details/999")

        assert exc_info.value.status_code == 404
        assert "/entity-activity-details/999" in str(exc_info.value)

    def test_require_data_returns_the_resource_when_present(self) -> None:
        doc = BackstopApiResourceDocument[_Attrs].model_validate(
            {"data": {"id": "1", "type": "party", "attributes": {"name": "Acme"}}}
        )

        assert doc.require_data(path="/party/1").id == "1"

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


class TestIncludedResource:
    """Reading one entry of an `included` array — what `follow_included` hands back."""

    def test_keeps_the_identity_alongside_the_parsed_attributes(self) -> None:
        entry = included_resource(
            {"id": "42", "type": "products", "attributes": {"name": "Acme"}},
            schema=IncludedResource[_Attrs],
        )

        assert entry is not None
        assert (entry.id, entry.type, entry.attributes.name) == ("42", "products", "Acme")

    def test_null_relationships_does_not_reject_the_entry(self) -> None:
        """`BackstopApiResource` declares `relationships`, so a wire null fails it — not here."""
        entry = included_resource(
            {"id": "42", "type": "products", "attributes": {"name": "Acme"}, "relationships": None},
            schema=IncludedResource[_Attrs],
        )

        assert entry is not None

    def test_nothing_to_read_is_none_rather_than_a_branch_at_the_call_site(self) -> None:
        assert included_resource(None, schema=IncludedResource[_Attrs]) is None

    def test_an_entry_that_does_not_validate_is_dropped_on_its_own(self) -> None:
        assert (
            included_resource({"id": "42", "type": "products"}, schema=IncludedResource[_Attrs])
            is None
        )

    def test_a_blank_id_is_dropped_like_a_missing_one(self) -> None:
        assert (
            included_resource(
                {"id": "  ", "type": "products", "attributes": {"name": "Acme"}},
                schema=IncludedResource[_Attrs],
            )
            is None
        )

    def test_absent_attributes_still_yields_the_identity_when_the_schema_allows_it(self) -> None:
        """JSON:API permits a resource object with no `attributes` — that must not cost the id."""
        entry = included_resource(
            {"id": "42", "type": "products"}, schema=IncludedResource[_OptionalAttrs]
        )

        assert entry is not None
        assert (entry.id, entry.attributes.name) == ("42", None)

    def test_the_json_api_type_is_optional(self) -> None:
        entry = included_resource(
            {"id": "42", "attributes": {"name": "Acme"}}, schema=IncludedResource[_Attrs]
        )

        assert entry is not None
        assert entry.type is None
