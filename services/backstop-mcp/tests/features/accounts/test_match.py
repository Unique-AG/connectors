from backstop_mcp.features.accounts.api_responses import ProductAttributes
from backstop_mcp.features.accounts.internal_dto import ResolvedProductDto
from backstop_mcp.features.accounts.product import (
    match_product,
    product_label,
)
from backstop_mcp.features.resolution import Ambiguous, NotFound, Resolved

CGUP = ResolvedProductDto(
    id="1292283",
    name="Capstone Global Unconstrained Portfolio",
    short_name="CGUP",
)
BLUC_I = ResolvedProductDto(id="100", name="Blue Capital I", short_name="BLUC")
BLUC_II = ResolvedProductDto(id="101", name="Blue Capital II", short_name="BLUC")
ALPHA_GROWTH = ResolvedProductDto(id="200", name="Alpha Growth Fund", short_name="AGRW")
ALPHA_VALUE = ResolvedProductDto(id="201", name="Alpha Value Fund", short_name="AVAL")
NO_SHORT = ResolvedProductDto(id="600", name="No Short Name Fund", short_name=None)
NAMELESS = ResolvedProductDto(id="700", name=None, short_name="NONM")

CATALOG = (CGUP, BLUC_I, BLUC_II, ALPHA_GROWTH, ALPHA_VALUE, NO_SHORT, NAMELESS)


class TestExactId:
    def test_exact_id_resolves(self) -> None:
        result = match_product(CATALOG, "1292283")

        assert isinstance(result, Resolved)
        assert result.value == CGUP

    def test_id_match_is_case_sensitive(self) -> None:
        products = (ResolvedProductDto(id="AbC", name="Other", short_name="OTHR"),)

        result = match_product(products, "abc")

        assert isinstance(result, NotFound)

    def test_id_is_matched_before_short_name(self) -> None:
        colliding = (
            ResolvedProductDto(id="CGUP", name="Something Else", short_name="OTHER"),
            CGUP,
        )

        result = match_product(colliding, "CGUP")

        assert isinstance(result, Resolved)
        assert result.value.id == "CGUP"


class TestExactShortName:
    def test_exact_short_name_resolves(self) -> None:
        result = match_product(CATALOG, "CGUP")

        assert isinstance(result, Resolved)
        assert result.value == CGUP

    def test_short_name_match_is_case_insensitive(self) -> None:
        result = match_product(CATALOG, "cgup")

        assert isinstance(result, Resolved)
        assert result.value.id == "1292283"

    def test_duplicate_short_name_is_ambiguous(self) -> None:
        result = match_product(CATALOG, "BLUC")

        assert isinstance(result, Ambiguous)
        assert result.query == "BLUC"
        assert result.scope == "products"
        assert [candidate.value.id for candidate in result.candidates] == ["100", "101"]

    def test_nameless_product_resolves_by_short_name(self) -> None:
        result = match_product(CATALOG, "NONM")

        assert isinstance(result, Resolved)
        assert result.value == NAMELESS


class TestExactName:
    def test_exact_name_resolves(self) -> None:
        result = match_product(CATALOG, "Capstone Global Unconstrained Portfolio")

        assert isinstance(result, Resolved)
        assert result.value == CGUP

    def test_name_match_is_case_insensitive(self) -> None:
        result = match_product(CATALOG, "capstone global unconstrained portfolio")

        assert isinstance(result, Resolved)
        assert result.value == CGUP

    def test_exact_name_is_matched_before_substring(self) -> None:
        result = match_product(CATALOG, "Blue Capital I")

        assert isinstance(result, Resolved)
        assert result.value == BLUC_I


class TestSubstringName:
    def test_unique_substring_resolves(self) -> None:
        result = match_product(CATALOG, "Unconstrained")

        assert isinstance(result, Resolved)
        assert result.value == CGUP

    def test_shared_substring_is_ambiguous(self) -> None:
        result = match_product(CATALOG, "Alpha")

        assert isinstance(result, Ambiguous)
        assert [candidate.value.id for candidate in result.candidates] == ["200", "201"]

    def test_substring_is_case_insensitive(self) -> None:
        result = match_product(CATALOG, "unconstrained")

        assert isinstance(result, Resolved)
        assert result.value == CGUP


class TestNoMatch:
    def test_no_match_is_not_found(self) -> None:
        result = match_product(CATALOG, "Does Not Exist")

        assert isinstance(result, NotFound)
        assert result.query == "Does Not Exist"
        assert result.scope == "products"

    def test_empty_query_is_not_found(self) -> None:
        result = match_product(CATALOG, "")

        assert isinstance(result, NotFound)
        assert result.query == ""
        assert result.scope == "products"

    def test_whitespace_only_query_is_not_found(self) -> None:
        result = match_product(CATALOG, "   ")

        assert isinstance(result, NotFound)
        assert result.query == ""
        assert result.scope == "products"


class TestLabel:
    def test_label_includes_short_name_when_present(self) -> None:
        assert product_label(CGUP) == "Capstone Global Unconstrained Portfolio (CGUP)"

    def test_label_is_name_alone_when_there_is_no_short_name(self) -> None:
        assert product_label(NO_SHORT) == "No Short Name Fund"

    def test_candidate_key_is_the_product_id(self) -> None:
        result = match_product(CATALOG, "BLUC")

        assert isinstance(result, Ambiguous)
        assert [candidate.key for candidate in result.candidates] == ["100", "101"]
        assert [candidate.label for candidate in result.candidates] == [
            "Blue Capital I (BLUC)",
            "Blue Capital II (BLUC)",
        ]


class TestProductFromAttributes:
    def test_reads_nested_product_short_name(self) -> None:
        attributes = ProductAttributes.model_validate(
            {
                "name": "Capstone Global Unconstrained Portfolio",
                "configuration": {"productShortName": "CGUP"},
            }
        )

        assert ResolvedProductDto.from_attributes("1292283", attributes) == CGUP

    def test_missing_configuration_leaves_short_name_unset(self) -> None:
        attributes = ProductAttributes.model_validate({"name": "No Short Name Fund"})

        assert ResolvedProductDto.from_attributes("600", attributes) == NO_SHORT
