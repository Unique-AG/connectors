from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.index import build_index, resolve_in_index
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


class TestNormalizeEntityType:
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


class TestResolveInIndex:
    def test_exact_crm_name(self) -> None:
        index = build_index([_def(definition_id="1", crm_name="Investor Status")])
        result = resolve_in_index(index, entity_type="organizations", query="investor status")
        assert isinstance(result, Resolved)
        assert result.value.definition_id == "1"

    def test_alias_match(self) -> None:
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

    def test_unknown_entity_type_returns_not_found(self) -> None:
        index = build_index([_def(definition_id="1", crm_name="Investor Status")])
        result = resolve_in_index(index, entity_type="spaceships", query="status")
        assert isinstance(result, NotFound)
        assert result.scope == "spaceships"
        assert result.query == "status"

    def test_ambiguous(self) -> None:
        index = build_index(
            [
                _def(definition_id="1", crm_name="North Status"),
                _def(definition_id="2", crm_name="South Status"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="status")
        assert isinstance(result, Ambiguous)
        assert len(result.candidates) == 2

    def test_partial_scoring_prefers_clear_best_match(self) -> None:
        index = build_index(
            [
                _def(definition_id="1", crm_name="Investor Grade"),
                _def(definition_id="2", crm_name="Grade Review Date"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="grade")
        assert isinstance(result, Resolved)
        # starts-with on "grade review date" outranks query-in-name on "investor grade"
        assert result.value.definition_id == "2"

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
