from pydantic import BaseModel

from backstop_mcp.backstop_client.json_api import JsonApiDocument, JsonApiResource


class _Attrs(BaseModel):
    name: str


class TestJsonApiDocument:
    def test_single_resource_validates_typed_attributes(self) -> None:
        doc = JsonApiDocument[_Attrs].model_validate(
            {"data": {"id": "1", "type": "party", "attributes": {"name": "Acme"}}}
        )

        assert isinstance(doc.data, JsonApiResource)
        assert doc.data.id == "1"
        assert doc.data.type == "party"
        assert isinstance(doc.data.attributes, _Attrs)
        assert doc.data.attributes.name == "Acme"

    def test_collection_validates_list_of_typed_resources(self) -> None:
        doc = JsonApiDocument[_Attrs].model_validate(
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
        doc = JsonApiDocument[_Attrs].model_validate({"data": None})

        assert doc.data is None
