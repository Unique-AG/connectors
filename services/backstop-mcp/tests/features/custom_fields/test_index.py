from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.index import build_index, resolve_in_index
from backstop_mcp.features.custom_fields.service import create_custom_fields_service
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.features.resolution import Ambiguous, NotFound, Resolved


def _def(
    *,
    id: str,
    entity_type: str = "OrganizationBean",
    name: str,
    is_time_series: bool = False,
) -> CustomFieldDefinition:
    return CustomFieldDefinition(
        id=id,
        entity_type=entity_type,
        name=name,
        is_time_series=is_time_series,
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
    def test_exact_name(self) -> None:
        index = build_index([_def(id="1", name="Investor Status")])
        result = resolve_in_index(index, entity_type="organizations", query="investor status")
        assert isinstance(result, Resolved)
        assert result.value.id == "1"

    def test_id_match(self) -> None:
        index = build_index([_def(id="cf-99", name="Investor Status")])
        result = resolve_in_index(index, entity_type="organizations", query="cf-99")
        assert isinstance(result, Resolved)
        assert result.value.name == "Investor Status"

    def test_fuzzy_grade(self) -> None:
        index = build_index([_def(id="2", name="Investor Grade")])
        result = resolve_in_index(index, entity_type="organizations", query="grade")
        assert isinstance(result, Resolved)

    def test_unknown_entity_type_returns_not_found(self) -> None:
        index = build_index([_def(id="1", name="Investor Status")])
        result = resolve_in_index(index, entity_type="spaceships", query="status")
        assert isinstance(result, NotFound)
        assert result.scope == "spaceships"
        assert result.query == "status"

    def test_ambiguous(self) -> None:
        index = build_index(
            [
                _def(id="1", name="North Status"),
                _def(id="2", name="South Status"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="status")
        assert isinstance(result, Ambiguous)
        assert len(result.candidates) == 2

    def test_partial_scoring_prefers_clear_best_match(self) -> None:
        index = build_index(
            [
                _def(id="1", name="Investor Grade"),
                _def(id="2", name="Grade Review Date"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="grade")
        assert isinstance(result, Resolved)
        # starts-with on "grade review date" outranks query-in-name on "investor grade"
        assert result.value.id == "2"

    def test_not_found(self) -> None:
        index = build_index([_def(id="1", name="Grade")])
        result = resolve_in_index(index, entity_type="organizations", query="missing")
        assert isinstance(result, NotFound)

    def test_exact_match_outranks_partial_matches(self) -> None:
        """Without tiering, an exact hit drowns in its own near-misses and every lookup prompts."""
        index = build_index(
            [
                _def(id="1", name="Grade"),
                _def(id="2", name="Grade Review Date"),
                _def(id="3", name="Investor Grade"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="Grade")
        assert isinstance(result, Resolved)
        assert result.value.id == "1"

    def test_several_exact_matches_are_still_ambiguous(self) -> None:
        index = build_index(
            [
                _def(id="1", name="Grade"),
                _def(id="2", name="grade"),
            ]
        )
        result = resolve_in_index(index, entity_type="organizations", query="Grade")
        assert isinstance(result, Ambiguous)
        assert {c.key for c in result.candidates} == {"1", "2"}

    def test_scope_is_reported_on_unresolved_outcomes(self) -> None:
        """`query`/`scope` are the shared vocabulary every resolver reports (see resolution.py)."""
        result = resolve_in_index(build_index([]), entity_type="organizations", query="grade")
        assert isinstance(result, NotFound)
        assert result.query == "grade"
        assert result.scope == "organizations"

    def test_products_and_party_resolve_by_tool_name(self) -> None:
        index = build_index(
            [
                _def(id="p1", entity_type="ProductBean", name="Share Class"),
                _def(id="y1", entity_type="PartyBean", name="KYC Status"),
            ]
        )
        product = resolve_in_index(index, entity_type="products", query="Share Class")
        assert isinstance(product, Resolved)
        assert product.value.id == "p1"
        party = resolve_in_index(index, entity_type="party", query="KYC Status")
        assert isinstance(party, Resolved)
        assert party.value.id == "y1"

    def test_contacts_and_employees_are_not_index_keys(self) -> None:
        index = build_index([_def(id="1", name="Grade")])
        for entity_type in ("contacts", "employees"):
            result = resolve_in_index(index, entity_type=entity_type, query="Grade")
            assert isinstance(result, NotFound)
            assert result.scope == entity_type

    def test_blank_query_is_not_found(self) -> None:
        index = build_index([_def(id="1", name="Grade")])
        result = resolve_in_index(index, entity_type="organizations", query="   ")
        assert isinstance(result, NotFound)


class TestDefinitionsForIndexKeys:
    def test_retrieves_product_and_party_rows_by_tool_name(self) -> None:
        service = create_custom_fields_service(ttl_minutes=60)
        subject = "index-keys"
        entry = service._entry(subject)  # pyright: ignore[reportPrivateUsage]
        entry.index = build_index(
            [
                _def(id="p1", entity_type="ProductBean", name="Share Class"),
                _def(id="y1", entity_type="PartyBean", name="KYC Status"),
            ]
        )

        assert [d.name for d in service.definitions_for("products", subject=subject)] == [
            "Share Class"
        ]
        assert [d.name for d in service.definitions_for("party", subject=subject)] == ["KYC Status"]
        assert service.definitions_for("contacts", subject=subject) == []
        assert service.definitions_for("employees", subject=subject) == []
