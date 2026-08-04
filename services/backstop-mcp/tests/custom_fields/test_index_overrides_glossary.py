import json

import pytest

from backstop_mcp.config import BackstopConfig, CustomFieldOverrideConfig
from backstop_mcp.custom_fields.glossary import format_glossary
from backstop_mcp.custom_fields.index import build_index, resolve_in_index
from backstop_mcp.custom_fields.overrides import normalize_entity_type, parse_override_key
from backstop_mcp.custom_fields.types import (
    AllowedValue,
    CustomFieldDefinition,
    FieldAmbiguous,
    FieldNotFound,
    FieldResolved,
)


def _def(
    *,
    definition_id: str,
    entity_type: str = "organizations",
    crm_name: str,
    display_name: str | None = None,
    aliases: tuple[str, ...] = (),
    is_time_series: bool = False,
    allowed: tuple[AllowedValue, ...] = (),
) -> CustomFieldDefinition:
    return CustomFieldDefinition(
        definition_id=definition_id,
        entity_type=entity_type,
        crm_name=crm_name,
        display_name=display_name or crm_name,
        aliases=aliases,
        is_time_series=is_time_series,
        allowed_values=allowed,
    )


class TestOverridesParsing:
    def test_parse_override_key(self) -> None:
        assert parse_override_key("organizations:is1") == (
            "organizations",
            "is1",
        )

    def test_parse_override_key_rejects_bad_shape(self) -> None:
        with pytest.raises(ValueError, match="entityType:crmName"):
            parse_override_key("organizations")

    def test_parse_override_key_splits_on_first_colon_only(self) -> None:
        """crmName may itself contain colons, so only the first separator is significant."""
        assert parse_override_key("organizations:1:is1") == ("organizations", "1:is1")

    def test_normalize_entity_type(self) -> None:
        assert normalize_entity_type("Organization") == "organizations"
        assert normalize_entity_type("people") == "people"

    def test_backstop_config_parses_overrides_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "BACKSTOP_CUSTOM_FIELD_OVERRIDES",
            json.dumps(
                {
                    "organizations:is1": {
                        "display_name": "Investor Status",
                        "aliases": ["investor status", "status"],
                    }
                }
            ),
        )
        config = BackstopConfig()
        override = config.custom_field_overrides["organizations:is1"]
        assert isinstance(override, CustomFieldOverrideConfig)
        assert override.display_name == "Investor Status"
        assert override.aliases == ["investor status", "status"]


class TestResolveInIndex:
    def test_exact_crm_name(self) -> None:
        index = build_index([_def(definition_id="1", crm_name="Investor Status")])
        result = resolve_in_index(index, entity_type="organizations", query="investor status")
        assert isinstance(result, FieldResolved)
        assert result.definition.definition_id == "1"

    def test_alias_from_override_display(self) -> None:
        index = build_index(
            [
                _def(
                    definition_id="1",
                    crm_name="is1",
                    display_name="Investor Status",
                    aliases=("status",),
                )
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="status")
        assert isinstance(result, FieldResolved)
        assert result.definition.display_name == "Investor Status"

    def test_fuzzy_grade(self) -> None:
        index = build_index([_def(definition_id="2", crm_name="Investor Grade")])
        result = resolve_in_index(index, entity_type="organizations", query="grade")
        assert isinstance(result, FieldResolved)

    def test_ambiguous(self) -> None:
        index = build_index(
            [
                _def(definition_id="1", crm_name="Investor Status"),
                _def(definition_id="2", crm_name="Account Status"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="status")
        assert isinstance(result, FieldAmbiguous)
        assert len(result.candidates) == 2

    def test_not_found(self) -> None:
        index = build_index([_def(definition_id="1", crm_name="Grade")])
        result = resolve_in_index(index, entity_type="organizations", query="missing")
        assert isinstance(result, FieldNotFound)


class TestGlossary:
    def test_empty_definitions_render_nothing(self) -> None:
        assert format_glossary([], entity_type="organizations") == ""

    def test_includes_allowed_values_and_truncates(self) -> None:
        definitions = [
            _def(
                definition_id=str(i),
                crm_name=f"Field {i}",
                allowed=(AllowedValue(id="a", label="A"),),
            )
            for i in range(50)
        ]
        text = format_glossary(definitions, entity_type="organizations", budget_chars=400)
        assert "Custom field glossary (organizations)" in text
        assert "truncated" in text
