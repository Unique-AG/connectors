import pytest
from pydantic import BaseModel, ValidationError

from backstop_mcp.backstop_client.json_api import BackstopApiDocument, BackstopApiResource


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
