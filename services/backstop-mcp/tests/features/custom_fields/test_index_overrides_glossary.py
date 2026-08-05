import json

import pytest

from backstop_mcp.config import BackstopConfig, CustomFieldOverrideConfig
from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.glossary import format_glossaries, format_glossary
from backstop_mcp.features.custom_fields.index import build_index, resolve_in_index
from backstop_mcp.features.custom_fields.overrides import parse_override_key
from backstop_mcp.features.custom_fields.types import AllowedValue, CustomFieldDefinition
from backstop_mcp.features.resolution import Ambiguous, NotFound, Resolved


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

    def test_party_search_types_are_known_entity_types(self) -> None:
        from backstop_mcp.features.entity_types import (
            KNOWN_ENTITY_TYPES,
            PARTY_SEARCH_TYPES,
            is_party_search_type,
        )

        assert set(PARTY_SEARCH_TYPES) <= set(KNOWN_ENTITY_TYPES)
        assert is_party_search_type("Organization")
        assert not is_party_search_type("opportunities")

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
        assert isinstance(result, Resolved)
        assert result.value.definition_id == "1"

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
        assert isinstance(result, Resolved)
        assert result.value.display_name == "Investor Status"

    def test_fuzzy_grade(self) -> None:
        index = build_index([_def(definition_id="2", crm_name="Investor Grade")])
        result = resolve_in_index(index, entity_type="organizations", query="grade")
        assert isinstance(result, Resolved)

    def test_ambiguous(self) -> None:
        index = build_index(
            [
                _def(definition_id="1", crm_name="Investor Status"),
                _def(definition_id="2", crm_name="Account Status"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="status")
        assert isinstance(result, Ambiguous)
        assert len(result.candidates) == 2

    def test_not_found(self) -> None:
        index = build_index([_def(definition_id="1", crm_name="Grade")])
        result = resolve_in_index(index, entity_type="organizations", query="missing")
        assert isinstance(result, NotFound)

    def test_exact_match_outranks_partial_matches(self) -> None:
        """Without tiering, an exact hit drowns in its own near-misses and every lookup prompts."""
        index = build_index(
            [
                _def(definition_id="1", crm_name="Grade"),
                _def(definition_id="2", crm_name="Grade Review Date"),
                _def(definition_id="3", crm_name="Investor Grade"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="Grade")
        assert isinstance(result, Resolved)
        assert result.value.definition_id == "1"

    def test_several_exact_matches_are_still_ambiguous(self) -> None:
        index = build_index(
            [
                _def(definition_id="1", crm_name="Grade"),
                _def(definition_id="2", crm_name="grade"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="Grade")
        assert isinstance(result, Ambiguous)
        assert {c.key for c in result.candidates} == {"1", "2"}

    def test_scope_is_reported_on_unresolved_outcomes(self) -> None:
        """`query`/`scope` are the shared vocabulary every resolver reports (see resolution.py)."""
        result = resolve_in_index(build_index([]), entity_type="Organization", query="grade")
        assert isinstance(result, NotFound)
        assert result.query == "grade"
        assert result.scope == "organizations"

    def test_blank_query_is_not_found(self) -> None:
        index = build_index([_def(definition_id="1", crm_name="Grade")])
        result = resolve_in_index(index, entity_type="organizations", query="   ")
        assert isinstance(result, NotFound)


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

    def test_a_budget_too_small_for_any_entry_renders_nothing(self) -> None:
        """A bare header would be noise in a tool description, and mislead about coverage."""
        definitions = [_def(definition_id="1", crm_name="Investor Status")]
        assert format_glossary(definitions, entity_type="organizations", budget_chars=40) == ""


class TestGlossaries:
    def test_several_entities_share_one_budget(self) -> None:
        """The budget bounds the whole tool description, not each entity type separately."""
        entities = [
            (
                entity,
                [
                    _def(definition_id=f"{entity}-{i}", entity_type=entity, crm_name=f"Field {i}")
                    for i in range(50)
                ],
            )
            for entity in ("organizations", "contacts", "people")
        ]

        text = format_glossaries(entities, budget_chars=1_000)

        # Exactly the budget, not the budget plus a truncation notice: the notice is reserved
        # before a line is admitted, so a block can no longer overrun and hand the next entity
        # type a negative remainder.
        assert len(text) <= 1_000
        assert "Custom field glossary (organizations)" in text
        assert "Custom field glossary (people)" not in text

    def test_entities_with_no_definitions_are_skipped(self) -> None:
        text = format_glossaries(
            [
                ("organizations", []),
                ("contacts", [_def(definition_id="1", entity_type="contacts", crm_name="Title")]),
            ]
        )

        assert "Custom field glossary (organizations)" not in text
        assert "Custom field glossary (contacts)" in text


class TestGlossaryBudgetIsNeverExceeded:
    """The notice used to be appended after the budget check, so a block overran by its length —
    and `format_glossaries` then spent a negative remainder on the entity types that followed."""

    @pytest.mark.parametrize("budget", [60, 120, 200, 400, 1_000, 5_000])
    def test_one_block_stays_within_its_budget_at_every_size(self, budget: int) -> None:
        definitions = [
            _def(definition_id=str(i), crm_name=f"Field {i}", aliases=("alias-a", "alias-b"))
            for i in range(60)
        ]

        text = format_glossary(definitions, entity_type="organizations", budget_chars=budget)

        assert len(text) <= budget

    @pytest.mark.parametrize("budget", [200, 400, 900, 2_000])
    def test_the_shared_budget_bounds_every_block_together(self, budget: int) -> None:
        entities = [
            (
                entity,
                [
                    _def(definition_id=f"{entity}-{i}", entity_type=entity, crm_name=f"Field {i}")
                    for i in range(30)
                ],
            )
            for entity in ("organizations", "contacts", "people", "employees")
        ]

        assert len(format_glossaries(entities, budget_chars=budget)) <= budget

    def test_a_later_entity_is_not_dropped_while_budget_remains(self) -> None:
        """The overrun's real cost: an entity type silently omitted for an unrelated reason."""
        entities = [
            ("organizations", [_def(definition_id="1", crm_name="Investor Status")]),
            ("contacts", [_def(definition_id="2", entity_type="contacts", crm_name="Title")]),
        ]

        text = format_glossaries(entities, budget_chars=5_000)

        assert "Custom field glossary (organizations)" in text
        assert "Custom field glossary (contacts)" in text
