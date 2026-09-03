from pydantic import BaseModel, TypeAdapter

from backstop_mcp.lenient import LenientBool, LenientFloat, LenientInt, LenientStr


class _Flags(BaseModel):
    flag: LenientBool = None
    count: LenientInt = None
    amount: LenientFloat = None
    name: LenientStr = None


def test_valid_scalars_parse() -> None:
    parsed = _Flags.model_validate({"flag": True, "count": 3, "amount": 1.5, "name": "  Koch  "})

    assert parsed == _Flags(flag=True, count=3, amount=1.5, name="Koch")


def test_junk_scalars_become_none() -> None:
    parsed = _Flags.model_validate(
        {"flag": "not-a-bool", "count": "nope", "amount": "not-a-number", "name": 42}
    )

    assert parsed == _Flags()


def test_blank_strings_become_none() -> None:
    parsed = _Flags.model_validate({"flag": "  ", "count": "", "amount": "", "name": "  "})

    assert parsed == _Flags()


def test_absent_fields_default_to_none() -> None:
    assert _Flags.model_validate({}) == _Flags()


def test_adapters_accept_pydantic_coercions() -> None:
    assert TypeAdapter(LenientBool).validate_python("yes") is True
    assert TypeAdapter(LenientInt).validate_python("3") == 3
    assert TypeAdapter(LenientFloat).validate_python("1.5") == 1.5
    assert TypeAdapter(LenientStr).validate_python(" Koch ") == "Koch"
    assert TypeAdapter(LenientStr).validate_python(42) is None
