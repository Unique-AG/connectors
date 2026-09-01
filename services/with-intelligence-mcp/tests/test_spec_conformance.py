"""Our hand-written wire models, checked field-by-field against the vendor's own schemas.

The bug this exists for: the models were transcribed from the spec's field *names* without
reading its nested schemas, so `address.country` was declared `str` when the API sends an
object. Everything passed, because the test fixture was invented in the same wrong shape — it
agreed with the code instead of with the API.

The snapshot in `tests/spec/vendor_schemas.json` is pruned to the schemas we model, so a
refresh (`uv run agent-explore/spec.py snapshot`) is a readable diff of the contract we depend
on. This checks transcription, not live behaviour: whether a field is ever populated, and
whether the spec itself is honest, only a recorded response can settle.
"""

import json
import pathlib
import types
import typing
from typing import get_args, get_origin

import pytest
from pydantic import BaseModel

from with_intelligence_mcp.features.investors.api_responses import (
    AddressAttributes,
    AumRangeAttributes,
    ClassificationAttributes,
    ConsultantAttributes,
    CurrencyAttributes,
    EntityAttributes,
    InvestorExtendedAttributes,
    InvestorListItemAttributes,
    LatestAumAttributes,
    StateAttributes,
    StrategyGroupAttributes,
)
from with_intelligence_mcp.features.persons.api_responses import (
    PersonExtendedAttributes,
    PersonListItemAttributes,
    PersonRoleAttributes,
    RoleOrganisationAttributes,
)
from with_intelligence_mcp.with_intelligence_client import PageInfo

_SNAPSHOT = pathlib.Path(__file__).parent / "spec" / "vendor_schemas.json"

# Our model -> the vendor schema it transcribes.
MODELS: dict[type[BaseModel], str] = {
    InvestorListItemAttributes: "Investor",
    InvestorExtendedAttributes: "InvestorExtended",
    ClassificationAttributes: "Classification",
    EntityAttributes: "Entity",
    CurrencyAttributes: "InvestorCurrency",
    StateAttributes: "InvestorAddressState",
    LatestAumAttributes: "InvestorLatestAum",
    AddressAttributes: "InvestorAddress",
    ConsultantAttributes: "InvestorConsultant",
    StrategyGroupAttributes: "InvestorInvestmentStrategies",
    AumRangeAttributes: "InvestorLatestAumRangesUsd",
    PersonListItemAttributes: "Person",
    PersonExtendedAttributes: "PersonExtended",
    PersonRoleAttributes: "PersonPersonRole",
    RoleOrganisationAttributes: "PersonPersonRolesOrganisation",
    PageInfo: "PaginatedResponsePagination",
}

# Places we knowingly differ, with the reason. A deviation that is not listed is a bug.
#
# Three of these are the spec being wrong rather than us: it declares single objects and arrays
# in place of each other, which a recorded response settles and this file cannot. Each one was
# found by a real call, so add to `tests/features/investors/recordings` before adding here.
DELIBERATE: dict[tuple[type[BaseModel], str], str] = {
    (
        InvestorExtendedAttributes,
        "preferences",
    ): "passed through untouched rather than modelled: it is an add-on payload we only relay",
    (
        InvestorExtendedAttributes,
        "investment_strategies",
    ): "declared an object, delivered as a list — see tests/features/investors/recordings",
    (
        LatestAumAttributes,
        "ranges_usd",
    ): "declared a single object, delivered as a list of them",
    (
        StrategyGroupAttributes,
        "secondary_strategies",
    ): "declared a single Classification, delivered as a list of them",
}


def _schemas() -> dict[str, dict[str, object]]:
    loaded = typing.cast("dict[str, object]", json.loads(_SNAPSHOT.read_text()))
    schemas = loaded["schemas"]
    assert isinstance(schemas, dict)
    return typing.cast("dict[str, dict[str, object]]", schemas)


def _properties(schema_name: str) -> dict[str, dict[str, object]]:
    schema = _schemas().get(schema_name)
    assert schema is not None, f"{schema_name} is not in the snapshot"
    properties = schema.get("properties", {})
    assert isinstance(properties, dict)
    return typing.cast("dict[str, dict[str, object]]", properties)


def _type_args(annotation: object) -> list[object]:
    return list(typing.cast("tuple[object, ...]", get_args(annotation)))


def _unwrap_optional(annotation: object) -> object:
    """`X | None` -> `X`. Both union spellings, since the codebase uses the operator form."""
    if get_origin(annotation) is not types.UnionType:
        return annotation
    args = [arg for arg in _type_args(annotation) if arg is not type(None)]
    return args[0] if len(args) == 1 else annotation


def _our_kind(annotation: object) -> tuple[str, object]:
    """Reduce one of our annotations to `(kind, detail)` for comparison."""
    inner = _unwrap_optional(annotation)
    origin = get_origin(inner)
    if origin is list:
        return ("list", _our_kind(_type_args(inner)[0]))
    if origin is dict:
        return ("object", None)
    if isinstance(inner, type):
        if issubclass(inner, BaseModel):
            return ("model", inner)
        if inner is str:
            return ("string", None)
        if inner is bool:
            return ("boolean", None)
        if inner in (int, float):
            return ("number", None)
        return ("unknown", inner.__name__)
    return ("unknown", repr(inner))


def _spec_kind(prop: dict[str, object]) -> tuple[str, object]:
    """Reduce one spec property to the same `(kind, detail)` shape."""
    reference = prop.get("$ref")
    if isinstance(reference, str):
        return ("model", reference.rsplit("/", 1)[-1])

    all_of = prop.get("allOf")
    if isinstance(all_of, list):
        entries = typing.cast("list[object]", all_of)
        if entries and isinstance(entries[0], dict):
            return _spec_kind(typing.cast("dict[str, object]", entries[0]))

    declared = prop.get("type")
    if declared == "array":
        items = prop.get("items", {})
        assert isinstance(items, dict)
        return ("list", _spec_kind(typing.cast("dict[str, object]", items)))
    if declared == "integer":
        return ("number", None)
    if isinstance(declared, str):
        return (declared, None)
    return ("unknown", declared)


def _matches(ours: tuple[str, object], theirs: tuple[str, object]) -> bool:
    our_kind, our_detail = ours
    their_kind, their_detail = theirs
    if our_kind != their_kind:
        return False
    if our_kind == "list":
        assert isinstance(our_detail, tuple) and isinstance(their_detail, tuple)
        return _matches(
            typing.cast("tuple[str, object]", our_detail),
            typing.cast("tuple[str, object]", their_detail),
        )
    if our_kind == "model":
        # The nested class has to transcribe the schema the vendor actually references.
        assert isinstance(our_detail, type)
        return MODELS.get(typing.cast("type[BaseModel]", our_detail)) == their_detail
    return True


_PAIRS = list(MODELS.items())


class TestEveryDeclaredFieldExists:
    @pytest.mark.parametrize(("model", "schema_name"), _PAIRS)
    def test_no_field_is_absent_from_the_schema(
        self, model: type[BaseModel], schema_name: str
    ) -> None:
        properties = _properties(schema_name)
        missing = [name for name in model.model_fields if name not in properties]
        assert missing == [], (
            f"{model.__name__} declares fields {schema_name} does not have: {missing}"
        )


class TestEveryDeclaredFieldHasTheRightType:
    @pytest.mark.parametrize(("model", "schema_name"), _PAIRS)
    def test_types_match_the_schema(self, model: type[BaseModel], schema_name: str) -> None:
        properties = _properties(schema_name)
        wrong: list[str] = []
        for name, field in model.model_fields.items():
            if (model, name) in DELIBERATE or name not in properties:
                continue
            ours = _our_kind(field.annotation)
            theirs = _spec_kind(properties[name])
            if not _matches(ours, theirs):
                wrong.append(f"{name}: we say {ours[0]}, spec says {theirs[0]} ({theirs[1]})")
        assert wrong == [], f"{model.__name__} does not match {schema_name}: {wrong}"


class TestTheDetectionItself:
    """Vacuous conformance checks are worse than none, so prove each comparison fires."""

    def test_the_snapshot_is_present_and_populated(self) -> None:
        assert len(_schemas()) > 10

    def test_every_registered_model_has_fields_to_check(self) -> None:
        empty = [model.__name__ for model in MODELS if not model.model_fields]
        assert empty == []

    def test_a_string_where_the_spec_says_object_is_caught(self) -> None:
        """Exactly the bug: `country` declared `str` when the vendor sends a Classification."""
        assert not _matches(_our_kind(str | None), ("model", "Classification"))

    def test_the_real_nested_declaration_passes(self) -> None:
        assert _matches(_our_kind(ClassificationAttributes | None), ("model", "Classification"))

    def test_a_wrong_nested_model_is_caught(self) -> None:
        """Right kind, wrong schema — `country: CurrencyAttributes` must not pass."""
        assert not _matches(_our_kind(CurrencyAttributes | None), ("model", "Classification"))

    def test_a_list_of_the_wrong_model_is_caught(self) -> None:
        assert not _matches(
            _our_kind(list[ClassificationAttributes]), ("list", ("model", "Entity"))
        )

    def test_a_list_of_the_right_model_passes(self) -> None:
        assert _matches(_our_kind(list[EntityAttributes]), ("list", ("model", "Entity")))

    def test_a_number_declared_as_a_string_is_caught(self) -> None:
        assert not _matches(_our_kind(str | None), ("number", None))

    def test_int_and_float_both_satisfy_the_specs_number(self) -> None:
        """The vendor types every id as `number`; we narrow to int at our own boundary."""
        assert _matches(_our_kind(int | None), ("number", None))
        assert _matches(_our_kind(float | None), ("number", None))

    def test_allof_is_followed_to_its_reference(self) -> None:
        """`preferences` is an allOf wrapper, which must resolve rather than read as unknown."""
        assert _spec_kind({"allOf": [{"$ref": "#/components/schemas/InvestorPreferences"}]}) == (
            "model",
            "InvestorPreferences",
        )

    def test_every_deliberate_deviation_names_a_real_field(self) -> None:
        for model, field in DELIBERATE:
            assert field in model.model_fields, f"{model.__name__} has no field {field}"
