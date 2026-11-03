"""Each test pins a discrepancy that forces a hand-written model or a call_untyped call in the
upstream layer. When one fails, the vendor spec (or the codegen) has caught up: drop the override
the test names and let the generated model stand.
"""

from pathlib import Path
from typing import cast

from pydantic import AwareDatetime
import yaml

from world_check_mcp.upstream.generated.vendor_requests import MRZGenerationRequestInput
from world_check_mcp.upstream.generated.vendor_responses import AbstractScreeningResult
from world_check_mcp.upstream.generated.vendor_responses import UserSummaryDetails

_SPEC: object = cast(
    object,
    yaml.safe_load(
        (
            Path(__file__).resolve().parents[1] / "src/world_check_mcp/upstream/openapi.yml"
        ).read_text()
    ),
)


def _obj(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast(list[object], value)


def _schema(name: str) -> dict[str, object]:
    return _obj(_obj(_obj(_obj(_SPEC)["components"])["schemas"])[name])


def _responses(operation_id: str) -> dict[str, object]:
    for item in _obj(_obj(_SPEC)["paths"]).values():
        for operation in _obj(item).values():
            if not isinstance(operation, dict):
                continue
            typed = cast(dict[str, object], operation)
            if typed.get("operationId") == operation_id:
                return _obj(typed["responses"])
    raise AssertionError(f"{operation_id} is not in the spec")


def _has_json_success(responses: dict[str, object]) -> bool:
    for code, body in responses.items():
        content = _obj(body).get("content")
        if (
            code.startswith("2")
            and isinstance(content, dict)
            and "application/json" in cast(dict[str, object], content)
        ):
            return True
    return False


def test_generated_result_model_still_drops_the_passport_mrz_lines() -> None:
    """Justifies upstream.queries.ResultWire and upstream.actions.ScreeningMatchWire: the spec puts
    mrzLine1-3 on a passport result subtype that the codegen collapses into the base.
    """
    assert not any(name.startswith("mrz_line") for name in AbstractScreeningResult.model_fields)


def test_spec_still_types_review_required_as_a_boolean() -> None:
    """Justifies upstream.queries.ProviderCountWire and ScreeningStatusWire: the API sends the
    review-required count where the spec declares a boolean.
    """
    review_required = _obj(_obj(_schema("CaseResultsSummary")["properties"])["reviewRequired"])
    assert review_required["type"] == "boolean"


def test_spec_case_still_narrows_a_field_the_base_leaves_optional() -> None:
    """Justifies upstream.case.CaseWire: the generated Case makes name required over the optional
    name on AbstractCase, which the type check rejects as an incompatible override.
    """
    assert "name" not in _list(_schema("AbstractCase").get("required") or [])
    narrowed = [_obj(part).get("required", []) for part in _list(_schema("NewCase")["allOf"])]
    assert any("name" in cast(list[object], required) for required in narrowed)


def test_spec_toggle_still_answers_a_success_with_an_empty_body() -> None:
    """Justifies widening the toggle response to None: a 204 carries no body, but the codegen types
    only the 200 model.
    """
    assert not _obj(_responses("toggleOngoingScreeningByProviderTypes")["204"]).get("content")


def test_spec_passport_verification_still_returns_no_json_body() -> None:
    """Justifies upstream.actions.VERIFY_PASSPORT staying a hand-written Operation[None] called
    through call_untyped: without a 2xx JSON body the codegen cannot model the operation.
    """
    assert not _has_json_success(_responses("mrzDataValidation"))


def test_spec_resolve_results_still_returns_no_json_body() -> None:
    """Justifies upstream.actions.RESOLVE_RESULTS staying a hand-written Operation[None] called
    through call_untyped: without a 2xx JSON body the codegen cannot model the operation.
    """
    assert not _has_json_success(_responses("resolveResults"))


def test_generated_user_summary_still_requires_fields_the_api_sends_as_null() -> None:
    """Justifies upstream.queries.CaseHitWire and CaseSearchWire: the generated CaseSearchResponse
    nests UserSummaryDetails with a required email, which the API returns as null.
    """
    assert UserSummaryDetails.model_fields["email"].annotation is str


def test_generated_mrz_request_still_types_the_date_of_birth_as_a_datetime() -> None:
    """Justifies generate_mrz calling getMrzData through call_untyped: the spec types dateOfBirth as
    a date-time, so a typed request would reject the date the passport carries.
    """
    assert MRZGenerationRequestInput.model_fields["date_of_birth"].annotation is AwareDatetime
