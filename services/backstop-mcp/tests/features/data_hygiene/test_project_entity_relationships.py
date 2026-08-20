"""`project_entity_relationships`: pull employment side-loads out of a by-id document."""

from pydantic import BaseModel

from backstop_mcp.backstop_client import BackstopApiResourceDocument
from backstop_mcp.features.data_hygiene import project_entity_relationships


class _Attrs(BaseModel):
    name: str


class TestEntityRelationships:
    def test_follows_relationships_and_selects_types_by_resource_type(self) -> None:
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
                    {
                        "type": "entity-relationship-types",
                        "id": "t1",
                        "attributes": {"name": "is employee of"},
                    },
                    {"type": "entity-relationships", "id": "er2", "attributes": {}},
                    {
                        "type": "people",
                        "id": "other",
                        "attributes": {"name": "noise"},
                    },
                ],
            }
        )

        result = project_entity_relationships(document)

        assert [item.id for item in result.relationships] == ["er2", "er1"]
        assert [item.id for item in result.relationship_types] == ["t1"]
        assert result.relationship_types[0].attributes.name == "is employee of"
