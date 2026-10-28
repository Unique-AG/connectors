import pydantic
import pytest

from mcp_observability.failed_fields import failed_fields

_CANARY = "zq-canary-value"


class Attribute(pydantic.BaseModel):
    name: str
    tags: tuple[str, ...] = ()


class Record(pydantic.BaseModel):
    attributes: list[Attribute]


def _failure(raw: object) -> pydantic.ValidationError:
    with pytest.raises(pydantic.ValidationError) as caught:
        Record.model_validate(raw)
    return caught.value


def test_names_the_path_pydantic_reports_and_the_type_of_the_input() -> None:
    failure = _failure({"attributes": [{"name": "ok"}, {"name": 5}]})

    assert failed_fields([failure]) == ["attributes.1.name (string_type, got int)"]


def test_writes_a_tuple_input_as_the_type_of_each_item() -> None:
    failure = _failure({"attributes": [{"name": ("Jane", 7)}]})

    assert failed_fields([failure]) == ["attributes.0.name (string_type, got tuple(str, int))"]


def test_writes_another_container_input_as_the_types_it_holds() -> None:
    name: dict[str, list[object]] = {_CANARY: [_CANARY, 1]}
    failure = _failure({"attributes": [{"name": name}]})

    assert failed_fields([failure]) == [
        "attributes.0.name (string_type, got dict[str, list[int | str]])"
    ]


def test_a_missing_field_names_no_input() -> None:
    nameless: dict[str, object] = {}
    failure = _failure({"attributes": [nameless]})

    assert failed_fields([failure]) == ["attributes.0.name (missing)"]


def test_never_carries_the_input() -> None:
    failure = _failure({"attributes": [{"name": {_CANARY: _CANARY}, "tags": [_CANARY, 5]}]})

    assert _CANARY not in str(failed_fields([failure]))


def test_lists_each_entry_once_in_the_order_pydantic_reported_it() -> None:
    first = _failure({"attributes": [{"name": 1}, {"name": 2}]})
    second = _failure({"attributes": "not a list"})

    assert failed_fields([first, TimeoutError("slow"), second, first]) == [
        "attributes.0.name (string_type, got int)",
        "attributes.1.name (string_type, got int)",
        "attributes (list_type, got str)",
    ]


def test_follows_the_cause_to_a_validation_error() -> None:
    try:
        raise RuntimeError(_CANARY) from _failure({"attributes": [{"name": 5}]})
    except RuntimeError as error:
        assert failed_fields([error]) == ["attributes.0.name (string_type, got int)"]


def test_follows_the_context_behind_raise_from_none() -> None:
    try:
        try:
            raise _failure({"attributes": [{"name": 5}]})
        except pydantic.ValidationError:
            raise RuntimeError(_CANARY) from None
    except RuntimeError as error:
        assert failed_fields([error]) == ["attributes.0.name (string_type, got int)"]


def test_looks_inside_an_exception_group() -> None:
    group = ExceptionGroup("batch", [_failure({"attributes": "not a list"})])

    assert failed_fields([group]) == ["attributes (list_type, got str)"]


def test_lists_an_exception_groups_members_in_their_order() -> None:
    group = ExceptionGroup(
        "batch",
        [_failure({"attributes": "not a list"}), _failure({"attributes": [{"name": 5}]})],
    )

    assert failed_fields([group]) == [
        "attributes (list_type, got str)",
        "attributes.0.name (string_type, got int)",
    ]


def test_is_empty_without_a_validation_error() -> None:
    assert failed_fields([RuntimeError(_CANARY)]) == []
