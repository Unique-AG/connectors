import pytest
from pydantic import BaseModel, ValidationError

from backstop_mcp.backstop_client.errors import BackstopUnexpectedCollectionError
from backstop_mcp.backstop_client.json_api import (
    BackstopApiDocument,
    BackstopApiResource,
    single_resource,
)


class _Attrs(BaseModel):
    name: str


class TestBackstopApiDocument:
    def test_single_resource_validates_typed_attributes(self) -> None:
        doc = BackstopApiDocument[_Attrs].model_validate(
            {"data": {"id": "1", "type": "party", "attributes": {"name": "Acme"}}}
        )

        assert isinstance(doc.data, BackstopApiResource)
        assert doc.data.id == "1"
        assert doc.data.type == "party"
        assert isinstance(doc.data.attributes, _Attrs)
        assert doc.data.attributes.name == "Acme"

    def test_collection_validates_list_of_typed_resources(self) -> None:
        doc = BackstopApiDocument[_Attrs].model_validate(
            {
                "data": [
                    {"id": "1", "type": "party", "attributes": {"name": "Acme"}},
                    {"id": "2", "type": "party", "attributes": {"name": "Globex"}},
                ]
            }
        )

        assert isinstance(doc.data, list)
        assert [item.attributes.name for item in doc.data] == ["Acme", "Globex"]

    def test_null_data_validates_to_none(self) -> None:
        doc = BackstopApiDocument[_Attrs].model_validate({"data": None})

        assert doc.data is None


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


class TestSingleResource:
    """A by-id read that comes back as a list is a malformed upstream response.

    `get_organization` used to `assert` on this, which would have surfaced an `AssertionError`
    (not a `ToolError`) to the MCP client — and asserting on data from a system boundary is
    exactly what the repo's own guidance reserves `throw` for.
    """

    def test_returns_the_resource_for_a_single_document(self) -> None:
        document = BackstopApiDocument[_Attrs].model_validate(
            {"data": {"id": "1", "type": "organizations", "attributes": {"name": "Capstone"}}}
        )

        resource = single_resource(document, path="/organizations/1")

        assert resource is not None
        assert resource.id == "1"

    def test_returns_none_for_a_document_describing_nothing(self) -> None:
        document = BackstopApiDocument[_Attrs].model_validate({"data": None})

        assert single_resource(document, path="/organizations/1") is None

    def test_raises_a_typed_error_for_a_collection(self) -> None:
        document = BackstopApiDocument[_Attrs].model_validate(
            {"data": [{"id": "1", "type": "organizations", "attributes": {"name": "Capstone"}}]}
        )

        with pytest.raises(BackstopUnexpectedCollectionError) as excinfo:
            _ = single_resource(document, path="/organizations/1")

        # The path is carried so the failure names the request that produced it.
        assert excinfo.value.path == "/organizations/1"
        assert "/organizations/1" in str(excinfo.value)

    def test_raises_for_an_empty_collection_too(self) -> None:
        """An empty list is still the wrong *shape*, not merely an absent record."""
        document = BackstopApiDocument[_Attrs].model_validate({"data": []})

        with pytest.raises(BackstopUnexpectedCollectionError):
            _ = single_resource(document, path="/organizations/1")
