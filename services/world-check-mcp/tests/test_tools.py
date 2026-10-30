import json
from typing import cast

from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import StaticTokenVerifier
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp.shared.exceptions import MCPError
from mcp_types import ElicitResult
from pydantic import TypeAdapter
import pytest

from tests.offline_server import build_server
from tests.offline_server import fake_upstream_settings
from world_check_mcp.persistence import Persistence


def _token(request: httpx2.Request) -> httpx2.Response | None:
    if request.url.path != "/auth/oauth2/v1/token":
        return None
    return httpx2.Response(
        200, json={"access_token": "access-token", "token_type": "Bearer", "expires_in": 3600}
    )


_OBJECT = TypeAdapter(dict[str, object])


def _body(request: httpx2.Request) -> dict[str, object]:
    return _OBJECT.validate_json(request.content)


_screen_modes: list[str] = []
_writes: list[tuple[str, dict[str, object]]] = []


def _passport_template() -> httpx2.Response:
    passport_fields = [
        ("SFCT_8", "TEXT", "GIVEN NAME"),
        ("SFCT_9", "TEXT", "LAST NAME"),
        ("SFCT_10", "GENDER", "GENDER"),
        ("SFCT_11", "STATE", "ISSUING STATE"),
        ("SFCT_12", "STATE", "NATIONALITY"),
        ("SFCT_13", "DATE", "DATE OF BIRTH"),
        ("SFCT_14", "PASSPORT_DOCUMENT_TYPE", "DOCUMENT TYPE"),
        ("SFCT_15", "TEXT", "IDENTIFICATION NUMBER"),
        ("SFCT_16", "DATE", "DATE OF EXPIRY"),
    ]
    return _json(
        200,
        {
            "groupId": "g-passport",
            "groupScreeningType": "CASE_MANAGEMENT_AUDIT",
            "mandatoryProviderTypes": ["PASSPORT_CHECK"],
            "secondaryFieldsByProvider": {
                "PASSPORT_CHECK": {
                    "secondaryFieldsByEntity": {
                        "INDIVIDUAL": [
                            {
                                "typeId": type_id,
                                "fieldValueType": value_type,
                                "label": label,
                                "fieldRequired": True,
                            }
                            for type_id, value_type, label in passport_fields
                        ]
                    }
                },
                "WATCHLIST": {
                    "secondaryFieldsByEntity": {
                        "INDIVIDUAL": [
                            {
                                "typeId": "SFCT_2",
                                "fieldValueType": "COUNTRY",
                                "label": "NATIONALITY",
                                "fieldRequired": False,
                            }
                        ]
                    }
                },
            },
        },
    )


def _template(group_id: str, providers: list[str], *, required: bool) -> httpx2.Response:
    return _json(
        200,
        {
            "groupId": group_id,
            "groupScreeningType": "CASE_MANAGEMENT_AUDIT",
            "mandatoryProviderTypes": providers,
            "secondaryFieldsByProvider": {
                "WATCHLIST": {
                    "secondaryFieldsByEntity": {
                        "INDIVIDUAL": [
                            {
                                "typeId": "SFCT_2",
                                "fieldValueType": "COUNTRY",
                                "label": "NATIONALITY",
                                "fieldRequired": required,
                            }
                        ]
                    }
                }
            },
        },
    )


def _case(case_system_id: str, providers: list[str]) -> httpx2.Response:
    return _json(
        200,
        {
            "caseId": case_system_id,
            "caseSystemId": case_system_id,
            "name": "Ada Lovelace",
            "entityType": "INDIVIDUAL",
            "groupId": "g1",
            "providerTypes": providers,
        },
    )


def _screened(results: list[object]) -> dict[str, object]:
    return {
        "caseId": "new-1",
        "caseSystemId": "sys-new",
        "name": "Ada Lovelace",
        "entityType": "INDIVIDUAL",
        "groupId": "g-screen",
        "results": results,
    }


def _json(status: int, body: object) -> httpx2.Response:
    return httpx2.Response(status, json=json.loads(json.dumps(body)))


def _world_check(request: httpx2.Request) -> httpx2.Response:
    token = _token(request)
    if token is not None:
        return token
    path = request.url.path
    if path.endswith("/groups") and request.url.params.get("showAllChildGroups") == "true":
        return _json(
            200, [{"id": "g1", "name": "KYC", "childGroups": [{"id": "g2", "name": "EU"}]}]
        )
    if path.endswith("/groups/g-passport/case-template"):
        return _passport_template()
    if path.endswith("/groups/g-screen/case-template"):
        return _template("g-screen", ["WATCHLIST"], required=True)
    if path.endswith("/groups/g-media/case-template"):
        return _template("g-media", ["MEDIA_CHECK"], required=False)
    if path.endswith("/groups/g1/case-template"):
        return _json(
            200,
            {
                "groupId": "g1",
                "groupScreeningType": "CASE",
                "mandatoryProviderTypes": ["WATCHLIST"],
                "secondaryFieldsByProvider": {
                    "WATCHLIST": {
                        "secondaryFieldsByEntity": {
                            "INDIVIDUAL": [
                                {
                                    "typeId": "SFCT_5",
                                    "fieldValueType": "COUNTRY",
                                    "label": "NATIONALITY",
                                    "fieldRequired": True,
                                }
                            ]
                        }
                    }
                },
            },
        )
    if path.endswith("/groups/g1/resolution-toolkits"):
        return _json(
            200,
            {
                "WATCHLIST": {
                    "groupId": "g1",
                    "providerType": "WATCHLIST",
                    "resolutionFields": {
                        "statuses": [
                            {"id": "s1", "label": "Positive", "type": "POSITIVE"},
                            {"id": "s2", "label": "False", "type": "FALSE"},
                        ],
                        "risks": [{"id": "k1", "label": "High"}, {"id": "k2", "label": "Low"}],
                        "reasons": [{"id": "n1", "label": "Full match"}],
                    },
                    "resolutionRules": {
                        "s1": {
                            "risks": ["k1"],
                            "reasons": ["n1"],
                            "reasonRequired": False,
                            "remarkRequired": False,
                        },
                        "s2": {
                            "risks": ["k1"],
                            "reasons": ["n1"],
                            "reasonRequired": True,
                            "remarkRequired": True,
                        },
                    },
                }
            },
        )
    if path.endswith("/groups/g1"):
        return _json(200, {"id": "g1", "name": "KYC"})
    if "/references/cases/" in path and path.endswith("ext-1"):
        return _json(200, {"caseId": "ext-1", "caseSystemId": "sys-1"})
    if path.endswith("/cases/ext-1"):
        return httpx2.Response(404)
    if path.endswith("/cases/media-1"):
        return _case("media-1", ["MEDIA_CHECK"])
    if path.endswith("/cases/fail-1"):
        return _case("fail-1", ["WATCHLIST"])
    if request.method == "GET" and path.endswith("/cases/sys-pass"):
        return _json(
            200,
            {
                "caseId": "ext-pass",
                "caseSystemId": "sys-pass",
                "name": "Ada Lovelace",
                "entityType": "INDIVIDUAL",
                "groupId": "g1",
                "providerTypes": ["PASSPORT_CHECK", "WATCHLIST"],
                "lifecycleState": "UNARCHIVED",
            },
        )
    if request.method == "GET" and path.endswith("/cases/sys-bare"):
        return _case("sys-bare", ["PASSPORT_CHECK"])
    if request.method == "GET" and path.endswith("/cases/sys-1"):
        return _json(
            200,
            {
                "caseId": "ext-1",
                "caseSystemId": "sys-1",
                "name": "Ada Lovelace",
                "entityType": "INDIVIDUAL",
                "groupId": "g1",
                "providerTypes": ["WATCHLIST"],
                "lifecycleState": "UNARCHIVED",
            },
        )
    if path.endswith("/references/records/e_1"):
        return _json(
            200,
            {
                "entityType": "INDIVIDUAL",
                "referenceId": "e_1",
                "names": {"nameDetails": [{"details": [{"value": "Ada Lovelace"}]}]},
                "sources": [],
                "categories": [{"value": "PEP"}],
            },
        )
    if path.endswith("/references/countries"):
        return _json(200, {"GBR": "United Kingdom"})
    if path.endswith("/references/nationalities"):
        return _json(200, {"GBR": "British"})
    if path.endswith("/references/providers"):
        return _json(200, [{"code": "trwc", "identifier": "wc", "name": "World-Check"}])
    if path.endswith("/references/search-filters"):
        return _json(
            200,
            {
                "freeTextParameters": [
                    {"fields": ["primaryName"], "type": "QUERY", "valueType": "STRING"}
                ]
            },
        )
    if path.endswith("/apiInfo"):
        return _json(200, {"version": "3.9.0", "systemDateTime": "2026-10-22T06:47:00Z"})
    if path.endswith("/cases/search"):
        body = _body(request)
        assert body["sort"] == [{"columnName": "creationDate", "order": "DESCENDING"}]
        if body.get("query"):
            assert body["query"] == 'primaryName=="Ada"'
            assert body["filter"] == '(lifecycleState==UNARCHIVED);groupId=="g1"'
        else:
            assert body["filter"] == 'groupId=="g1"'
        return _json(
            200,
            {
                "results": [
                    {
                        "caseId": "ext-1",
                        "caseSystemId": "sys-1",
                        "name": "Ada Lovelace",
                        "entityType": "INDIVIDUAL",
                        "groupId": "g1",
                    }
                ],
                "pagination": {"pageReferences": {"next": "page-2"}},
            },
        )
    if path.endswith("/cases/sys-pass/results"):
        return _json(
            200,
            {
                "results": [
                    {
                        "resultId": "p1",
                        "providerType": "PASSPORT_CHECK",
                        "mrzLine1": "P<GBRLOVELACE<<ADA",
                        "mrzLine2": "1234567890GBR",
                    },
                    {
                        "resultId": "r9",
                        "referenceId": "e_1",
                        "providerType": "WATCHLIST",
                        "submittedTerm": "Ada Lovelace",
                    },
                ],
                "pagination": {"pageReferences": {}},
            },
        )
    if path.endswith("/cases/sys-bare/results"):
        return _json(
            200,
            {
                "results": [{"resultId": "p0", "providerType": "PASSPORT_CHECK"}],
                "pagination": {"pageReferences": {}},
            },
        )
    if path.endswith("/cases/sys-1/results"):
        return _json(
            200,
            {
                "results": [
                    {
                        "resultId": "r1",
                        "referenceId": "e_1",
                        "providerType": "WATCHLIST",
                        "matchStrength": "EXACT",
                        "submittedTerm": "Ada Lovelace",
                    }
                ],
                "pagination": {"pageReferences": {}},
            },
        )
    if path.endswith("/cases/screening-status"):
        body = _body(request)
        assert body["providerTypes"] == ["WATCHLIST", "PASSPORT_CHECK"]
        return _json(
            200,
            [
                {
                    "caseSystemId": "sys-1",
                    "screeningStatus": "SCREENED",
                    "providerSummaries": {
                        "WATCHLIST": {"totalMatches": 1, "reviewRequired": 0, "unresolved": 1}
                    },
                }
            ],
        )
    if path.endswith("/cases/sys-1/audit-events"):
        return _json(
            200,
            {
                "results": [
                    {
                        "id": "a1",
                        "actionType": "NEW_CASE",
                        "eventDate": "2026-10-22T06:47:00Z",
                        "actionedByUserName": "service-account",
                    }
                ],
                "pagination": {"pageReferences": {"next": None}},
            },
        )
    if path.endswith("/passport-check/mrz"):
        body = _body(request)
        assert body["issuingState"] == "GBR"
        assert body["nationality"] == "GBR"
        return _json(
            200, {"lines": ["P<GBRLOVELACE<<ADA", "1234567890GBR"], "conformWithICAO": True}
        )
    if request.method == "POST" and path.endswith("/cases"):
        body = _body(request)
        assert request.url.params.get("screen") == "SYNC"
        providers = cast(list[str], body["providerTypes"])
        assert "MEDIA_CHECK" not in providers
        if providers == ["WATCHLIST", "PASSPORT_CHECK"]:
            secondary = cast(list[dict[str, object]], body["secondaryFields"])
            assert {"typeId": "SFCT_8", "value": "Ada"} in secondary
            return _json(
                200,
                _screened(
                    [
                        {"resultId": "p1", "providerType": "PASSPORT_CHECK", "mrzLine1": "P<GBR"},
                        {"resultId": "r1", "providerType": "WATCHLIST"},
                        {"resultId": "r2", "providerType": "WATCHLIST"},
                    ]
                ),
            )
        assert providers == ["WATCHLIST"]
        assert body["caseScreeningState"] == {"WATCHLIST": "INITIAL"}
        assert body["secondaryFields"] == [{"typeId": "SFCT_2", "value": "GBR"}]
        return _json(
            200,
            _screened(
                [
                    {"resultId": "r1", "referenceId": "e_1", "providerType": "WATCHLIST"},
                    {"resultId": "r2", "referenceId": "e_2", "providerType": "WATCHLIST"},
                ]
            ),
        )
    if request.method == "PATCH" and path.endswith("/cases/sys-1"):
        if request.headers.get("content-type") != "application/json" or not request.content:
            return _json(404, [])
        _screen_modes.append(request.url.params["screen"])
        return _json(
            200,
            {
                **_screened(
                    [
                        {"resultId": "r1", "providerType": "WATCHLIST", "matchStrength": "EXACT"},
                        {"resultId": "p1", "providerType": "PASSPORT_CHECK", "mrzLine1": "P<UTO"},
                    ]
                ),
                "caseSystemId": "sys-1",
            },
        )
    if path.endswith("/bulk/cases/ongoing-screening"):
        body = _body(request)
        assert body["caseScreeningState"] == {"WATCHLIST": "ONGOING"}
        assert "MEDIA_CHECK" not in json.dumps(body)
        if body["caseSystemIds"] == ["fail-1"]:
            return _json(
                200,
                {
                    "failedCases": [
                        {
                            "caseSystemId": "fail-1",
                            "errors": [{"code": "DENIED", "message": "Case cannot be monitored."}],
                        }
                    ]
                },
            )
        return httpx2.Response(204)
    if path.endswith("/cases/ongoing-screening-updates"):
        body = _body(request)
        expression = str(body["filter"])
        assert "providerType==WATCHLIST" in expression
        assert "MEDIA" not in expression
        pagination = cast(dict[str, object], body["pagination"])
        if pagination.get("pageReference") == "none":
            return _json(
                404,
                {
                    "errors": [
                        {
                            "code": "NO_OGS_CASE_UPDATES_FOUND_WITHIN_DATE_RANGE",
                            "message": "No updates.",
                        }
                    ]
                },
            )
        assert 'groupId=="g1"' in expression
        return _json(
            200,
            {
                "results": [
                    {
                        "caseSystemId": "sys-1",
                        "caseId": "ext-1",
                        "groupId": "g1",
                        "updateDate": "2026-10-22T06:47:00Z",
                        "watchlistResults": {"numberOfNewResults": 1, "numberOfUpdatedResults": 0},
                    }
                ],
                "pagination": {"pageReferences": {"next": "page-2"}},
            },
        )
    if request.method == "PUT" and (
        path.endswith("/passport-check/verification") or path.endswith("/results/resolution")
    ):
        _writes.append((path, _body(request)))
        return httpx2.Response(204)
    return httpx2.Response(404)


def _server() -> FastMCP:
    return build_server(
        fake_upstream_settings(),
        Persistence(store=MemoryStore()),
        httpx2.MockTransport(_world_check),
    )


async def test_list_groups_returns_descendant_groups() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("list_groups", {})

    groups = result.structured_content
    assert groups is not None
    assert groups["result"][0]["child_groups"][0]["name"] == "EU"


async def test_get_group_settings_joins_the_template_and_toolkit() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_group_settings", {"group_id": "g1"})

    settings = result.structured_content
    assert settings is not None
    assert settings["secondary_fields"][0]["type_id"] == "SFCT_5"
    assert settings["toolkits"][0]["statuses"][0]["status_type"] == "POSITIVE"


async def test_get_case_resolves_an_external_id_after_the_internal_lookup_misses() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case", {"case": "ext-1"})

    details = result.structured_content
    assert details is not None
    assert details["case_system_id"] == "sys-1"
    assert details["name"] == "Ada Lovelace"


async def test_get_case_reference_returns_the_internal_id() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case_reference", {"case_id": "ext-1"})

    assert result.structured_content == {"case_id": "ext-1", "case_system_id": "sys-1"}


async def test_get_profile_uses_the_record_reference_id() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_profile", {"reference_id": "e_1"})

    profile = result.structured_content
    assert profile is not None
    assert profile["names"] == ["Ada Lovelace"]
    assert profile["categories"] == ["PEP"]


async def test_list_cases_filters_to_the_group() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("list_cases", {"group_id": "g1"})

    page = result.structured_content
    assert page is not None
    assert page["cases"][0]["case_system_id"] == "sys-1"
    assert page["next_page"] == "page-2"


async def test_search_cases_keeps_the_group_filter_with_the_query() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool(
            "search_cases",
            {
                "group_id": "g1",
                "query": 'primaryName=="Ada"',
                "expression": "lifecycleState==UNARCHIVED",
                "search_mode": "EXACT",
            },
        )

    page = result.structured_content
    assert page is not None
    assert page["cases"][0]["name"] == "Ada Lovelace"


async def test_get_case_results_resolves_an_external_case_id() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case_results", {"case": "ext-1"})

    results = result.structured_content
    assert results is not None
    assert results["case_system_id"] == "sys-1"
    assert results["matches"][0]["reference_id"] == "e_1"


async def test_get_screening_status_reports_watchlist_progress() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_screening_status", {"case": "sys-1"})

    status = result.structured_content
    assert status is not None
    assert status["screening_status"] == "SCREENED"
    assert status["providers"][0]["total_matches"] == 1


async def test_get_case_audit_events_returns_the_newest_event() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case_audit_events", {"case": "sys-1"})

    page = result.structured_content
    assert page is not None
    assert page["events"][0]["action_type"] == "NEW_CASE"
    assert page["next_page"] is None


async def test_get_reference_data_returns_country_codes() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_reference_data", {"kind": "countries"})

    assert result.structured_content == {
        "kind": "countries",
        "names_by_code": {"GBR": "United Kingdom"},
        "providers": None,
        "search_filters": None,
        "api_version": None,
        "system_date_time": None,
    }


async def test_screen_entity_persists_a_watchlist_case_and_truncates_matches() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool(
            "screen_entity",
            {
                "name": "Ada Lovelace",
                "entity_type": "INDIVIDUAL",
                "group_id": "g-screen",
                "nationality": "GBR",
                "limit": 1,
            },
        )

    outcome = result.structured_content
    assert outcome is not None
    assert outcome["case_system_id"] == "sys-new"
    assert outcome["watchlist_truncated"] is True
    assert outcome["watchlist_matches"][0]["result_id"] == "r1"
    assert outcome["watchlist_matches"][1:] == []
    assert outcome["passport_matches"] == []


async def test_screen_entity_refuses_an_existing_case_id() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="already exists"):
            await client.call_tool(
                "screen_entity",
                {
                    "name": "Ada Lovelace",
                    "entity_type": "INDIVIDUAL",
                    "group_id": "g-screen",
                    "case_id": "ext-1",
                    "nationality": "GBR",
                },
            )


async def test_screen_entity_requires_the_group_nationality() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="NATIONALITY"):
            await client.call_tool(
                "screen_entity",
                {"name": "Ada Lovelace", "entity_type": "INDIVIDUAL", "group_id": "g-screen"},
            )


async def test_screen_entity_refuses_a_group_that_requires_media_check() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="WATCHLIST-only"):
            await client.call_tool(
                "screen_entity",
                {
                    "name": "Ada Lovelace",
                    "entity_type": "INDIVIDUAL",
                    "group_id": "g-media",
                    "nationality": "GBR",
                },
            )


async def test_rescreen_case_refuses_media_check() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="Media Check"):
            await client.call_tool("rescreen_case", {"case": "media-1"})


async def test_rescreen_case_can_screen_only_changes_since_the_last_run() -> None:
    _screen_modes.clear()
    async with Client(_server()) as client:
        result = await client.call_tool("rescreen_case", {"case": "sys-1", "delta": True})

    outcome = result.structured_content
    assert _screen_modes == ["DELTA_SYNC"]
    assert outcome is not None
    assert outcome["passport_matches"][0]["mrz_line_1"] == "P<UTO"


async def test_enable_ongoing_screening_treats_an_empty_response_as_enabled() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("enable_ongoing_screening", {"case": "sys-1"})

    screening = result.structured_content
    assert screening is not None
    assert screening["enabled"] is True
    assert screening["provider_type"] == "WATCHLIST"


async def test_enable_ongoing_screening_reports_a_failure_body() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("enable_ongoing_screening", {"case": "fail-1"})

    screening = result.structured_content
    assert screening is not None
    assert screening["enabled"] is False
    assert screening["failures"] == ["Case cannot be monitored."]


async def test_get_ogs_updates_returns_watchlist_counts() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool(
            "get_ogs_updates",
            {
                "since": "2026-10-20T00:00:00Z",
                "until": "2026-10-22T00:00:00Z",
                "group_id": "g1",
            },
        )

    page = result.structured_content
    assert page is not None
    assert page["updates"][0]["new_results"] == 1
    assert page["next_page"] == "page-2"
    assert page["window"]["until"] == "2026-10-22T00:00:00Z"


async def test_get_ogs_updates_turns_no_updates_into_an_empty_page() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool(
            "get_ogs_updates",
            {
                "since": "2026-10-20T00:00:00Z",
                "until": "2026-10-22T00:00:00Z",
                "page_reference": "none",
            },
        )

    page = result.structured_content
    assert page is not None
    assert page["updates"] == []
    assert page["next_page"] is None


async def test_get_ogs_updates_requires_the_original_window_on_the_next_page() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="Reuse both since and until"):
            await client.call_tool("get_ogs_updates", {"page_reference": "page-2"})


_PASSPORT = {
    "given_name": "Ada",
    "last_name": "Lovelace",
    "gender": "FEMALE",
    "date_of_birth": "1815-12-10",
    "issuing_state": "gbr",
    "nationality": "GBR",
    "identification_number": "123456789",
    "date_of_expiry": "2030-01-01",
}


async def test_generate_passport_mrz_uses_nationality_codes() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("generate_passport_mrz", {"passport": _PASSPORT})

    mrz = result.structured_content
    assert mrz is not None
    assert mrz["lines"][0] == "P<GBRLOVELACE<<ADA"
    assert mrz["conforms_with_icao"] is True


async def test_generate_passport_mrz_rejects_a_watchlist_country_code() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="nationalities"):
            await client.call_tool(
                "generate_passport_mrz",
                {"passport": {**_PASSPORT, "issuing_state": "XXX"}},
            )


async def test_passport_check_screens_without_media_check() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool(
            "passport_check", {"passport": _PASSPORT, "group_id": "g-passport", "limit": 1}
        )

    check = result.structured_content
    assert check is not None
    assert check["case_system_id"] == "sys-new"
    assert check["passport_matches"][0]["mrz_line_1"] == "P<GBR"
    assert check["watchlist_truncated"] is True
    assert check["watchlist_matches"][1:] == []


async def test_passport_check_refuses_an_existing_case_id() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="already exists"):
            await client.call_tool(
                "passport_check",
                {"passport": _PASSPORT, "group_id": "g-passport", "case_id": "ext-1"},
            )


_messages: list[str] = []


async def _approve(
    message: str, _response_type: object, _params: object, _context: object
) -> dict[str, bool]:
    _messages.append(message)
    return {"approve": True}


async def _decline(
    _message: str, _response_type: object, _params: object, _context: object
) -> ElicitResult:
    return ElicitResult(action="decline")


async def test_verify_passport_check_saves_only_after_approval() -> None:
    _writes.clear()
    _messages.clear()
    async with Client(_server(), elicitation_handler=_approve) as client:
        result = await client.call_tool(
            "verify_passport_check",
            {"case": "sys-pass", "mrz_matched": True, "note": "Compared the document"},
        )

    saved = result.structured_content
    assert saved is not None
    assert saved["recorded"] is True
    assert saved["mrz_matched"] is True
    assert "MCP reviewer: local development (unauthenticated)" in saved["note"]
    assert "P<GBRLOVELACE<<ADA" in _messages[0]
    assert _writes[0][0].endswith("/passport-check/verification")
    assert _writes[0][1]["mrzMatched"] is True


async def test_verify_passport_check_decline_does_not_write() -> None:
    _writes.clear()
    async with Client(_server(), elicitation_handler=_decline) as client:
        result = await client.call_tool(
            "verify_passport_check", {"case": "sys-pass", "mrz_matched": False}
        )

    saved = result.structured_content
    assert saved is not None
    assert saved["recorded"] is False
    assert saved["status"] == "cancelled"
    assert _writes == []


async def test_verify_passport_check_refuses_a_case_without_an_mrz() -> None:
    _writes.clear()
    async with Client(_server(), elicitation_handler=_approve) as client:
        with pytest.raises(ToolError, match="No generated passport MRZ"):
            await client.call_tool(
                "verify_passport_check", {"case": "sys-bare", "mrz_matched": True}
            )

    assert _writes == []


async def test_resolve_result_saves_an_approved_watchlist_decision() -> None:
    _writes.clear()
    _messages.clear()
    async with Client(_server(), elicitation_handler=_approve) as client:
        result = await client.call_tool(
            "resolve_result",
            {"case": "sys-1", "result_id": "r1", "status": "POSITIVE", "risk": "High"},
        )

    saved = result.structured_content
    assert saved is not None
    assert saved["resolved"] is True
    assert saved["status_id"] == "s1"
    assert saved["risk_id"] == "k1"
    assert "Positive match" in _messages[0]
    body = _writes[0][1]
    assert body["resultIds"] == ["r1"]
    assert body["statusId"] == "s1"
    assert "MCP reviewer:" in str(body["resolutionRemark"])


async def test_resolve_result_decline_does_not_write() -> None:
    _writes.clear()
    async with Client(_server(), elicitation_handler=_decline) as client:
        result = await client.call_tool(
            "resolve_result",
            {"case": "sys-1", "result_id": "r1", "status": "s1", "risk": "k1"},
        )

    saved = result.structured_content
    assert saved is not None
    assert saved["resolved"] is False
    assert _writes == []


async def test_resolve_result_honours_toolkit_rules_before_approval() -> None:
    _writes.clear()
    async with Client(_server(), elicitation_handler=_approve) as client:
        with pytest.raises(ToolError, match="not allowed"):
            await client.call_tool(
                "resolve_result",
                {"case": "sys-1", "result_id": "r1", "status": "POSITIVE", "risk": "Low"},
            )
        with pytest.raises(ToolError, match="non-empty note"):
            await client.call_tool(
                "resolve_result",
                {
                    "case": "sys-1",
                    "result_id": "r1",
                    "status": "FALSE",
                    "risk": "High",
                    "reason": "n1",
                },
            )

    assert _writes == []


async def test_resolve_result_refuses_a_passport_match() -> None:
    _writes.clear()
    async with Client(_server(), elicitation_handler=_approve) as client:
        with pytest.raises(ToolError, match="WATCHLIST"):
            await client.call_tool(
                "resolve_result",
                {"case": "sys-pass", "result_id": "p1", "status": "POSITIVE", "risk": "High"},
            )

    assert _writes == []


_WRITE_CALLS = [
    pytest.param(
        "resolve_result",
        {"case": "sys-1", "result_id": "r1", "status": "POSITIVE", "risk": "High"},
        id="resolve_result",
    ),
    pytest.param(
        "verify_passport_check", {"case": "sys-pass", "mrz_matched": True}, id="verify_passport"
    ),
]


@pytest.mark.parametrize(("tool", "arguments"), _WRITE_CALLS)
async def test_a_write_tool_refuses_a_client_without_form_elicitation(
    tool: str, arguments: dict[str, object]
) -> None:
    _writes.clear()
    async with Client(_server(), mode="legacy") as client:
        with pytest.raises(ToolError, match="form elicitation. No write was performed"):
            await client.call_tool(tool, arguments)

    assert _writes == []


@pytest.mark.parametrize(("tool", "arguments"), _WRITE_CALLS)
async def test_a_write_tool_does_not_write_when_the_client_cannot_answer_the_approval(
    tool: str, arguments: dict[str, object]
) -> None:
    _writes.clear()
    async with Client(_server()) as client:
        with pytest.raises(MCPError, match="Elicitation not supported"):
            await client.call_tool(tool, arguments)

    assert _writes == []


@pytest.mark.parametrize(("tool", "arguments"), _WRITE_CALLS)
async def test_a_write_tool_refuses_a_caller_without_a_token_when_auth_is_on(
    tool: str, arguments: dict[str, object]
) -> None:
    _writes.clear()
    server = _server()
    server.auth = StaticTokenVerifier(tokens={})
    async with Client(server, elicitation_handler=_approve) as client:
        with pytest.raises(ToolError, match="Authentication is required"):
            await client.call_tool(tool, arguments)

    assert _writes == []


async def test_get_ogs_updates_rejects_a_future_end() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="last 30 days"):
            await client.call_tool(
                "get_ogs_updates",
                {"since": "2026-10-20T00:00:00Z", "until": "2999-01-01T00:00:00Z"},
            )
