import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import UTC
import json
import socket
from typing import cast, Self

from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import StaticTokenVerifier
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp.client import session
from mcp.shared.exceptions import MCPError
from mcp_configs import ServerSettings
from mcp_types import ElicitResult
from mcp_types import TextContent
from pydantic import AnyHttpUrl
from pydantic import TypeAdapter
import pytest
import uvicorn

from tests.offline_server import build_server
from tests.offline_server import fake_upstream_settings
from world_check_mcp.contexts.groups.models import GroupEntry
from world_check_mcp.contexts.groups.search import find_groups
from world_check_mcp.contexts.screening import derived_case_id
from world_check_mcp.mcp import http_app
from world_check_mcp.persistence import InMemoryCaseLocks
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
# The last entry is the case LSEG maps the external caseId "ext-1" to.
_ext_1_maps_to: list[str] = ["sys-1"]
_SCREENED_CASE_ID = derived_case_id(
    "WATCHLIST", "g-retry", "INDIVIDUAL", "Grace Hopper", None, None, None, None, None, None
)


def _passport_template() -> httpx2.Response:
    """Ids other groups do not use, so a passport field is found by its label."""
    passport_fields = [
        ("SFCT_108", "TEXT", "GIVEN NAME"),
        ("SFCT_109", "TEXT", "LAST NAME"),
        ("SFCT_110", "GENDER", "GENDER"),
        ("SFCT_111", "STATE", "ISSUING STATE"),
        ("SFCT_112", "STATE", "NATIONALITY"),
        ("SFCT_113", "DATE", "DATE OF BIRTH"),
        ("SFCT_114", "PASSPORT_DOCUMENT_TYPE", "DOCUMENT TYPE"),
        ("SFCT_115", "TEXT", "IDENTIFICATION NUMBER"),
        ("SFCT_116", "DATE", "DATE OF EXPIRY"),
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
                            },
                            {
                                "typeId": "SFCT_3",
                                "fieldValueType": "DATE",
                                "label": "DATE_OF_BIRTH",
                                "fieldRequired": False,
                            },
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
    if "/references/cases/" in path and path.endswith(
        (_SCREENED_CASE_ID, _SCREENED_PASSPORT_CASE_ID)
    ):
        return _json(200, {"caseId": "derived", "caseSystemId": "sys-screened"})
    if "/references/cases/" in path and path.endswith("ext-1"):
        return _json(200, {"caseId": "ext-1", "caseSystemId": _ext_1_maps_to[-1]})
    if "/references/cases/" in path and path.endswith("ext-nosys"):
        return _json(200, {"caseId": "ext-nosys", "caseSystemId": "sys-nosys"})
    if path.endswith("/cases/ext-nosys"):
        return httpx2.Response(404)
    if path.endswith("/cases/sys-nosys"):
        return _json(
            200,
            {
                "caseId": "ext-nosys",
                "name": "Ada Lovelace",
                "entityType": "INDIVIDUAL",
                "groupId": "g1",
                "providerTypes": [],
            },
        )
    if path.endswith("/cases/ext-1"):
        return httpx2.Response(404)
    if path.endswith("/cases/media-1"):
        return _case("media-1", ["MEDIA_CHECK"])
    if path.endswith("/cases/fail-1"):
        return _case("fail-1", ["WATCHLIST"])
    if path.endswith("/cases/empty-failures-1"):
        return _case("empty-failures-1", ["WATCHLIST"])
    if path.endswith("/cases/summary-failed-1"):
        return _case("summary-failed-1", ["WATCHLIST"])
    if path.endswith("/cases/no-cases-1"):
        return _case("no-cases-1", ["WATCHLIST"])
    if path.endswith("/cases/other-failed-1"):
        return _case("other-failed-1", ["WATCHLIST"])
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
                "names": {
                    "nameDetails": [
                        {"type": "AKA", "details": [{"type": "FULL_NAME", "value": "Countess A"}]},
                        {
                            "type": "PRIMARY",
                            "details": [
                                {"type": "FIRST_NAME", "value": "Ada"},
                                {"type": "FULL_NAME", "value": "Ada Lovelace"},
                            ],
                        },
                    ]
                },
                "sources": [],
                "categories": [{"value": "PEP"}],
                "sourceReferenceLinks": {
                    "sourceReferenceLinkDetails": [
                        {"uri": "ftp://registry.example.org/e_1"},
                        {"uri": "https://registry.example.org/officials/e_1", "tags": ["PDF"]},
                        {"uri": "https://news.example.com/2026/ada-lovelace-appointed"},
                    ]
                },
            },
        )
    if path.endswith("/references/records/e_2"):
        return _json(
            200,
            {
                "entityType": "INDIVIDUAL",
                "referenceId": "e_2",
                "names": {"nameDetails": [{"details": [{"value": "Grace Hopper"}]}]},
                "sources": [],
            },
        )
    if path.endswith("/references/records/e_3"):
        return _json(
            200,
            {
                "entityType": "INDIVIDUAL",
                "referenceId": "e_3",
                "names": {"nameDetails": [{"details": [{"value": "Mary Somerville"}]}]},
                "sources": [],
                "sourceReferenceLinks": {
                    "sourceReferenceLinkDetails": [
                        {"uri": "HTTPS://registry.example.org/officials/e_3"},
                    ]
                },
            },
        )
    if path.endswith("/references/records/e_4"):
        return _json(
            200,
            {
                "entityType": "INDIVIDUAL",
                "referenceId": "e_4",
                "names": {
                    "nameDetails": [
                        {
                            "type": "AKA",
                            "details": [{"type": "FULL_NAME", "value": "Queen of Code"}],
                        },
                        {
                            "type": "PRIMARY",
                            "details": [
                                {"type": "FIRST_NAME", "value": "Grace"},
                                {"type": "LAST_NAME", "value": "Hopper"},
                            ],
                        },
                    ]
                },
                "sources": [],
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
            assert body["filter"] in {
                'groupId=="g1"',
                '(primaryName=="Ada (Countess)");groupId=="g1"',
            }
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
                        # LSEG sends null email/status here; the generated model rejects it.
                        "creator": {"id": "u1", "name": "svc", "email": None, "status": None},
                        "modifier": {"id": "u1", "name": "svc", "email": None, "status": None},
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
                        "objectId": "sys-1",
                        "entityType": "CASE",
                        "actionType": "NEW_CASE",
                        "eventDate": "2026-10-22T06:47:00Z",
                        "actionedByUserId": "u1",
                        "actionedByUserName": "service-account",
                        "details": {"detailsType": "CASE"},
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
            assert {"typeId": "SFCT_108", "value": "Ada"} in secondary
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
        assert {"typeId": "SFCT_2", "value": "GBR"} in cast(list[object], body["secondaryFields"])
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
                    "summary": {"totalCases": 1, "success": 0, "failed": 1},
                    "failedCases": [
                        {
                            "caseSystemId": "fail-1",
                            "errors": [{"code": "DENIED", "message": "Case cannot be monitored."}],
                        }
                    ],
                },
            )
        if body["caseSystemIds"] == ["empty-failures-1"]:
            return _json(
                200,
                {"summary": {"totalCases": 1, "success": 1, "failed": 0}, "failedCases": []},
            )
        if body["caseSystemIds"] == ["summary-failed-1"]:
            return _json(
                200,
                {"summary": {"totalCases": 1, "success": 0, "failed": 1}, "failedCases": []},
            )
        if body["caseSystemIds"] == ["no-cases-1"]:
            return _json(200, {"summary": {"totalCases": 0, "failed": 0}})
        if body["caseSystemIds"] == ["other-failed-1"]:
            return _json(
                200,
                {
                    "summary": {"totalCases": 1, "success": 1, "failed": 0},
                    "failedCases": [
                        {
                            "caseSystemId": "someone-else",
                            "errors": [{"code": "DENIED", "message": "Not this case."}],
                        }
                    ],
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
                "filter": expression,
                "mode": "FULL",
                "sort": [{"columnName": "updateDate", "order": "ASCENDING"}],
                "totalResultCount": 1,
                "results": [
                    {"caseId": "ext-0", "groupId": "g1", "updateDate": "2026-10-22T06:40:00Z"},
                    {
                        "caseSystemId": "sys-1",
                        "caseId": "ext-1",
                        "groupId": "g1",
                        "updateDate": "2026-10-22T06:47:00Z",
                        "watchlistResults": {"numberOfNewResults": 1, "numberOfUpdatedResults": 0},
                    },
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
        Persistence(store=MemoryStore(), case_locks=InMemoryCaseLocks()),
        httpx2.MockTransport(_world_check),
    )


_GROUP_TREE: list[dict[str, object]] = [
    {
        "id": "g1",
        "name": "KYC",
        "childGroups": [
            {"id": "g2", "name": "EU Onboarding"},
            {"id": "g3", "name": "EU Monitoring"},
        ],
    },
    {"id": "g4", "name": "Third Party Due Diligence"},
]


def _counting_server(*, reject_save_for: str | None = None) -> tuple[FastMCP, list[str]]:
    """The server over a larger group tree, with the LSEG paths each request asked for.

    LSEG refuses to save the case named `reject_save_for`.
    """
    paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        if (
            reject_save_for is not None
            and request.method == "POST"
            and request.url.path.endswith("/cases")
            and _body(request).get("name") == reject_save_for
        ):
            return _json(400, {"error": "bad request"})
        if request.url.path.endswith("/groups") and request.url.params.get("showAllChildGroups"):
            return _json(200, _GROUP_TREE)
        return _world_check(request)

    server = build_server(
        fake_upstream_settings(),
        Persistence(store=MemoryStore(), case_locks=InMemoryCaseLocks()),
        httpx2.MockTransport(handler),
    )
    return server, paths


def _paths_to(paths: list[str], suffix: str) -> list[str]:
    return [path for path in paths if path.endswith(suffix)]


async def _screen(client: Client[FastMCPTransport], name: str) -> None:
    await client.call_tool(
        "screen_entity",
        {
            "name": name,
            "entity_type": "INDIVIDUAL",
            "group_id": "g-screen",
            "nationality": "GBR",
        },
    )


async def test_two_screenings_read_the_template_and_the_reference_lists_once() -> None:
    server, paths = _counting_server()
    async with Client(server) as client:
        await _screen(client, "Ada Lovelace")
        await _screen(client, "Grace Hopper")

    assert len(_paths_to(paths, "/groups/g-screen/case-template")) == 1
    assert len(_paths_to(paths, "/references/countries")) == 1
    assert len(_paths_to(paths, "/references/nationalities")) == 1


async def test_two_passport_checks_read_the_template_and_the_nationalities_once() -> None:
    server, paths = _counting_server()
    async with Client(server) as client:
        for passport in (_PASSPORT, {**_PASSPORT, "identification_number": "987654321"}):
            await client.call_tool(
                "passport_check", {"passport": passport, "group_id": "g-passport"}
            )

    assert len(_paths_to(paths, "/groups/g-passport/case-template")) == 1
    assert len(_paths_to(paths, "/references/nationalities")) == 1


async def test_reference_data_is_the_same_from_the_cache_and_api_info_is_never_cached() -> None:
    server, paths = _counting_server()
    async with Client(server) as client:
        for kind in ("countries", "nationalities", "providers", "search_filters"):
            first = (
                await client.call_tool("get_reference_data", {"kind": kind})
            ).structured_content
            second = (
                await client.call_tool("get_reference_data", {"kind": kind})
            ).structured_content
            assert first is not None
            assert first == second
        await client.call_tool("get_reference_data", {"kind": "api_info"})
        await client.call_tool("get_reference_data", {"kind": "api_info"})

    assert len(_paths_to(paths, "/references/countries")) == 1
    assert len(_paths_to(paths, "/references/nationalities")) == 1
    assert len(_paths_to(paths, "/references/providers")) == 1
    assert len(_paths_to(paths, "/references/search-filters")) == 1
    assert len(_paths_to(paths, "/apiInfo")) == 2


async def test_screening_reuses_the_countries_the_reference_tool_read() -> None:
    server, paths = _counting_server()
    async with Client(server) as client:
        await client.call_tool("get_reference_data", {"kind": "countries"})
        await _screen(client, "Ada Lovelace")

    assert len(_paths_to(paths, "/references/countries")) == 1


async def test_a_rejected_save_makes_the_next_screening_read_the_template_again() -> None:
    server, paths = _counting_server(reject_save_for="Reject Me")
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await _screen(client, "Reject Me")
        await _screen(client, "Ada Lovelace")

    assert len(_paths_to(paths, "/groups/g-screen/case-template")) == 2


class _StoreThatCountsExits(MemoryStore):
    """Postgres closes its pool when the store is exited, and FastMCP exits what a dependency
    returns if it is a context manager.
    """

    exits: int = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        self.exits += 1


async def test_a_tool_that_reads_the_cache_never_exits_the_store() -> None:
    store = _StoreThatCountsExits()
    paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/groups") and request.url.params.get("showAllChildGroups"):
            return _json(200, _GROUP_TREE)
        return _world_check(request)

    server = build_server(
        fake_upstream_settings(),
        Persistence(store=store, case_locks=InMemoryCaseLocks()),
        httpx2.MockTransport(handler),
    )
    async with Client(server) as client:
        await client.call_tool("list_groups", {})
        await client.call_tool("list_groups", {})

    assert store.exits == 0
    assert [path for path in paths if path.endswith("/groups")] == ["/groups"]


async def _group_ids(client: Client[FastMCPTransport], **arguments: object) -> list[str]:
    result = await client.call_tool("list_groups", arguments)
    page = result.structured_content
    assert page is not None
    return [group["id"] for group in cast(list[dict[str, str]], page["groups"])]


async def test_list_groups_returns_a_flat_page_with_parents_and_child_counts() -> None:
    server, _ = _counting_server()
    async with Client(server) as client:
        result = await client.call_tool("list_groups", {})

    page = result.structured_content
    assert page is not None
    groups = cast(list[dict[str, object]], page["groups"])
    assert [(group["id"], group["parent_id"], group["child_group_count"]) for group in groups] == [
        ("g1", None, 2),
        ("g2", "g1", 0),
        ("g3", "g1", 0),
        ("g4", None, 0),
    ]
    assert page["total"] == 4
    assert page["next_page"] is None


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"query": "eu"}, ["g3", "g2"]),
        ({"query": "Onbording"}, ["g2"]),
        ({"query": "due diligence third"}, ["g4"]),
        ({"query": "zzz"}, []),
        ({"parent_id": "g1"}, ["g2", "g3"]),
        ({"parent_id": "g1", "query": "monitoring"}, ["g3"]),
    ],
)
async def test_list_groups_finds_groups_by_words_typos_and_parent(
    arguments: dict[str, str], expected: list[str]
) -> None:
    server, _ = _counting_server()
    async with Client(server) as client:
        assert await _group_ids(client, **arguments) == expected


async def test_list_groups_pages_through_the_matches() -> None:
    server, _ = _counting_server()
    async with Client(server) as client:
        first = (await client.call_tool("list_groups", {"limit": 3})).structured_content
        assert first is not None
        assert first["next_page"] == "3"
        assert await _group_ids(client, limit=3, page_reference=first["next_page"]) == ["g4"]


async def test_list_groups_refuses_a_page_reference_it_did_not_hand_out() -> None:
    server, _ = _counting_server()
    async with Client(server) as client:
        with pytest.raises(ToolError, match="next_page"):
            await client.call_tool("list_groups", {"page_reference": "abc"})


async def test_list_groups_asks_lseg_once_while_the_cache_holds() -> None:
    server, paths = _counting_server()
    async with Client(server) as client:
        await client.call_tool("list_groups", {})
        await client.call_tool("list_groups", {"query": "eu"})

    assert [path for path in paths if path.endswith("/groups")] == ["/groups"]


async def test_get_group_settings_joins_the_template_and_toolkit() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_group_settings", {"group_id": "g1"})

    settings = result.structured_content
    assert settings is not None
    assert settings["secondary_fields"][0]["type_id"] == "SFCT_5"
    assert settings["toolkits"][0]["statuses"][0]["status_type"] == "POSITIVE"


async def test_get_group_settings_returns_only_the_section_asked_for() -> None:
    async with Client(_server()) as client:
        fields = (
            await client.call_tool("get_group_settings", {"group_id": "g1", "section": "fields"})
        ).structured_content
        toolkits = (
            await client.call_tool("get_group_settings", {"group_id": "g1", "section": "toolkits"})
        ).structured_content

    assert fields is not None
    assert toolkits is not None
    assert fields["secondary_fields"] and fields["toolkits"] is None
    assert toolkits["toolkits"] and toolkits["secondary_fields"] is None


async def test_get_group_settings_narrows_the_fields_by_entity_type_and_requirement() -> None:
    async with Client(_server()) as client:
        everything = (
            await client.call_tool("get_group_settings", {"group_id": "g1"})
        ).structured_content
        required = (
            await client.call_tool("get_group_settings", {"group_id": "g1", "required_only": True})
        ).structured_content
        organisations = (
            await client.call_tool(
                "get_group_settings", {"group_id": "g1", "entity_type": "ORGANISATION"}
            )
        ).structured_content

    assert everything is not None
    assert required is not None
    assert organisations is not None
    all_fields = cast(list[dict[str, object]], everything["secondary_fields"])
    assert all(
        field["required"] for field in cast(list[dict[str, object]], required["secondary_fields"])
    )
    assert {
        str(field["entity_type"]).casefold()
        for field in cast(list[dict[str, object]], organisations["secondary_fields"])
    } <= {"organisation"}
    assert len(cast(list[object], organisations["secondary_fields"])) < len(all_fields)


async def test_get_group_settings_asks_lseg_once_while_the_cache_holds() -> None:
    server, paths = _counting_server()
    async with Client(server) as client:
        await client.call_tool("get_group_settings", {"group_id": "g1"})
        await client.call_tool("get_group_settings", {"group_id": "g1", "section": "toolkits"})

    assert [path for path in paths if path.endswith("/groups/g1/case-template")] == [
        "/groups/g1/case-template"
    ]


async def test_get_case_resolves_an_external_id_after_the_internal_lookup_misses() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case", {"case": "ext-1"})

    details = result.structured_content
    assert details is not None
    assert details["case_system_id"] == "sys-1"
    assert details["name"] == "Ada Lovelace"
    assert details["matched_by"] == "case_id"


async def test_get_case_reports_an_internal_id_match() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case", {"case": "sys-1"})

    details = result.structured_content
    assert details is not None
    assert details["case_system_id"] == "sys-1"
    assert details["matched_by"] == "case_system_id"


async def test_get_case_falls_back_to_the_resolved_system_id_when_upstream_omits_it() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case", {"case": "ext-nosys"})

    details = result.structured_content
    assert details is not None
    assert details["case_system_id"] == "sys-nosys"


async def test_get_case_reference_returns_the_internal_id() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case_reference", {"case_id": "ext-1"})

    assert result.structured_content == {"case_id": "ext-1", "case_system_id": "sys-1"}


async def test_get_profile_uses_the_record_reference_id() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_profile", {"reference_id": "e_1"})

    profile = result.structured_content
    assert profile is not None
    assert profile["names"] == ["Countess A", "Ada", "Ada Lovelace"]
    assert profile["categories"] == ["PEP"]


async def test_get_profile_is_titled_by_the_primary_name_and_links_its_first_source_page() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_profile", {"reference_id": "e_1"})

    profile = result.structured_content
    assert profile is not None
    assert profile["name"] == "Ada Lovelace"
    assert profile["url"] == "https://registry.example.org/officials/e_1"


async def test_get_profile_has_no_link_when_lseg_cites_no_source_page() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_profile", {"reference_id": "e_2"})

    profile = result.structured_content
    assert profile is not None
    assert profile["name"] == "Grace Hopper"
    assert profile["url"] is None


async def test_get_profile_prefers_a_primary_name_part_to_an_aka_full_name() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_profile", {"reference_id": "e_4"})

    profile = result.structured_content
    assert profile is not None
    assert profile["name"] == "Grace"


async def test_get_profile_links_a_source_page_whose_scheme_is_uppercase() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_profile", {"reference_id": "e_3"})

    profile = result.structured_content
    assert profile is not None
    assert profile["url"] == "HTTPS://registry.example.org/officials/e_3"


def _texts(result: CallToolResult) -> list[TextContent]:
    assert all(isinstance(item, TextContent) for item in result.content)
    return cast(list[TextContent], result.content)


async def test_get_profile_sends_the_record_over_http_as_one_json_item() -> None:
    async with _serve_over_http(_server()) as url, Client(url) as client:
        result = await client.call_tool("get_profile", {"reference_id": "e_1"})

    (profile,) = _texts(result)
    assert profile.meta is None
    assert json.loads(profile.text) == result.structured_content
    assert result.structured_content is not None
    assert result.structured_content["name"] == "Ada Lovelace"


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


@pytest.mark.parametrize(
    "expression",
    ['lifecycleState==UNARCHIVED),groupId=="other"', "(lifecycleState==UNARCHIVED"],
)
async def test_search_cases_refuses_an_expression_that_could_escape_the_group_filter(
    expression: str,
) -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="Balance the parentheses"):
            await client.call_tool("search_cases", {"group_id": "g1", "expression": expression})


async def test_search_cases_accepts_a_parenthesis_inside_a_quoted_value() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool(
            "search_cases", {"group_id": "g1", "expression": 'primaryName=="Ada (Countess)"'}
        )

    assert result.structured_content is not None


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


@pytest.mark.parametrize("days_from_today", [-1, 0])
async def test_screen_entity_accepts_a_dob_up_to_today(days_from_today: int) -> None:
    born = (date.today() + timedelta(days=days_from_today)).isoformat()
    async with Client(_server()) as client:
        result = await client.call_tool(
            "screen_entity",
            {
                "name": "Ada Lovelace",
                "entity_type": "INDIVIDUAL",
                "group_id": "g-screen",
                "nationality": "GBR",
                "dob": born,
            },
        )

    assert result.structured_content is not None


async def test_screen_entity_refuses_a_future_dob() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="Date of birth cannot be in the future"):
            await client.call_tool(
                "screen_entity",
                {
                    "name": "Ada Lovelace",
                    "entity_type": "INDIVIDUAL",
                    "group_id": "g-screen",
                    "nationality": "GBR",
                    "dob": tomorrow,
                },
            )


async def test_screen_entity_refuses_a_malformed_case_id() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="String should match pattern"):
            await client.call_tool(
                "screen_entity",
                {
                    "name": "Ada Lovelace",
                    "entity_type": "INDIVIDUAL",
                    "group_id": "g-screen",
                    "case_id": "a//b",
                    "nationality": "GBR",
                },
            )


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


def _recording_server() -> tuple[FastMCP, list[dict[str, object]]]:
    """The server, with the body of each case LSEG was asked to save."""
    saved: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST" and request.url.path.endswith("/cases"):
            saved.append(_body(request))
        return _world_check(request)

    server = build_server(
        fake_upstream_settings(),
        Persistence(store=MemoryStore(), case_locks=InMemoryCaseLocks()),
        httpx2.MockTransport(handler),
    )
    return server, saved


async def test_screen_entity_saves_the_case_under_the_derived_id() -> None:
    server, saved = _recording_server()
    async with Client(server) as client:
        await client.call_tool(
            "screen_entity",
            {
                "name": "Ada Lovelace",
                "entity_type": "INDIVIDUAL",
                "group_id": "g-screen",
                "nationality": "GBR",
            },
        )

    expected = derived_case_id(
        "WATCHLIST", "g-screen", "INDIVIDUAL", "Ada Lovelace", None, "GBR", None, None, None, None
    )
    assert [body["caseId"] for body in saved] == [expected]


async def test_screen_entity_saves_the_case_under_the_id_the_caller_chose() -> None:
    server, saved = _recording_server()
    async with Client(server) as client:
        await client.call_tool(
            "screen_entity",
            {
                "name": "Ada Lovelace",
                "entity_type": "INDIVIDUAL",
                "group_id": "g-screen",
                "nationality": "GBR",
                "case_id": "chosen-1",
            },
        )

    assert [body["caseId"] for body in saved] == ["chosen-1"]


async def test_passport_check_saves_the_case_under_the_derived_id() -> None:
    server, saved = _recording_server()
    async with Client(server) as client:
        await client.call_tool("passport_check", {"passport": _PASSPORT, "group_id": "g-passport"})

    assert [body["caseId"] for body in saved] == [_passport_case_id("g-passport")]


@pytest.mark.parametrize("change", [{"gender": "MALE"}, {"last_name": "King"}])
async def test_passport_check_derives_another_id_when_a_screened_field_differs(
    change: dict[str, str],
) -> None:
    server, saved = _recording_server()
    async with Client(server) as client:
        for passport in (_PASSPORT, {**_PASSPORT, **change}):
            await client.call_tool(
                "passport_check",
                {"passport": passport, "group_id": "g-passport", "name": "Ada Lovelace"},
            )

    assert len({body["caseId"] for body in saved}) == 2


def test_a_group_without_a_name_does_not_break_a_search() -> None:
    groups = [
        GroupEntry(id="g1", name="", parent_id=None, child_group_count=0),
        GroupEntry(id="g2", name="   ", parent_id=None, child_group_count=0),
        GroupEntry(id="g3", name="EU Onboarding", parent_id=None, child_group_count=0),
    ]

    found = find_groups(groups, query="eu", parent_id=None)

    assert [group.id for group in found] == ["g3"]


def test_derived_case_id_ignores_case_and_spacing_and_tells_entities_apart() -> None:
    assert derived_case_id("a", " Grace   HOPPER ") == derived_case_id("A", "grace hopper")
    assert derived_case_id("a", "Grace Hopper") != derived_case_id(
        "a", "Grace Hopper", date(1906, 12, 9)
    )
    assert derived_case_id("a", "b", "c") != derived_case_id("a", "bc")


@pytest.mark.parametrize("name", ["Grace Hopper", "  grace   HOPPER "])
async def test_screen_entity_refuses_a_retry_of_the_same_details(name: str) -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match=r"already screened.*sys-screened.*rescreen_case"):
            await client.call_tool(
                "screen_entity",
                {"name": name, "entity_type": "INDIVIDUAL", "group_id": "g-retry"},
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


async def test_enable_ongoing_screening_treats_an_empty_failed_cases_list_as_enabled() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("enable_ongoing_screening", {"case": "empty-failures-1"})

    screening = result.structured_content
    assert screening is not None
    assert screening["enabled"] is True
    assert screening["failures"] == []


async def test_enable_ongoing_screening_reports_failure_for_a_failure_of_another_case() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("enable_ongoing_screening", {"case": "other-failed-1"})

    screening = result.structured_content
    assert screening is not None
    assert screening["enabled"] is False
    assert screening["failures"] == ["Not this case."]


async def test_enable_ongoing_screening_reports_failure_when_the_summary_counts_no_cases() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("enable_ongoing_screening", {"case": "no-cases-1"})

    screening = result.structured_content
    assert screening is not None
    assert screening["enabled"] is False
    assert screening["failures"] == ["LSEG did not enable monitoring."]


async def test_enable_ongoing_screening_reports_failure_when_the_summary_rules_out_success() -> (
    None
):
    async with Client(_server()) as client:
        result = await client.call_tool("enable_ongoing_screening", {"case": "summary-failed-1"})

    screening = result.structured_content
    assert screening is not None
    assert screening["enabled"] is False
    assert screening["failures"] == ["LSEG did not enable monitoring."]


async def test_enable_ongoing_screening_reports_a_failure_body() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("enable_ongoing_screening", {"case": "fail-1"})

    screening = result.structured_content
    assert screening is not None
    assert screening["enabled"] is False
    assert screening["failures"] == ["Case cannot be monitored."]


# LSEG keeps 30 days of updates and the tool refuses a window outside them, so the window the
# tests ask for moves with the clock.
_OGS_UNTIL = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
_OGS_SINCE = _OGS_UNTIL - timedelta(days=2)
_OGS_SINCE_STAMP = _OGS_SINCE.strftime("%Y-%m-%dT%H:%M:%SZ")
_OGS_UNTIL_STAMP = _OGS_UNTIL.strftime("%Y-%m-%dT%H:%M:%SZ")


async def test_get_ogs_updates_returns_watchlist_counts() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool(
            "get_ogs_updates",
            {
                "since": _OGS_SINCE_STAMP,
                "until": _OGS_UNTIL_STAMP,
                "group_id": "g1",
            },
        )

    page = result.structured_content
    assert page is not None
    updates = cast(list[dict[str, object]], page["updates"])
    assert [update["case_system_id"] for update in updates] == ["sys-1"]
    assert page["updates"][0]["new_results"] == 1
    assert page["next_page"] == "page-2"
    assert page["window"]["until"] == _OGS_UNTIL_STAMP


async def test_get_ogs_updates_turns_no_updates_into_an_empty_page() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool(
            "get_ogs_updates",
            {
                "since": _OGS_SINCE_STAMP,
                "until": _OGS_UNTIL_STAMP,
                "page_reference": "none",
            },
        )

    page = result.structured_content
    assert page is not None
    assert page["updates"] == []
    assert page["next_page"] is None


async def test_get_ogs_updates_refuses_a_page_larger_than_100() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="100"):
            await client.call_tool("get_ogs_updates", {"limit": 101})


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


def _passport_case_id(group_id: str) -> str:
    """The id of the passport check of `_PASSPORT`: one part for each field it screens."""
    return derived_case_id(
        "PASSPORT_CHECK",
        group_id,
        "PASSPORT",
        "123456789",
        "GBR",
        "GBR",
        date(1815, 12, 10),
        date(2030, 1, 1),
        "FEMALE",
        "Ada",
        "Lovelace",
        "Ada Lovelace",
        "True",
    )


_SCREENED_PASSPORT_CASE_ID = _passport_case_id("g-retry")


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


async def test_passport_check_refuses_a_retry_of_the_same_document() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match=r"already screened.*sys-screened"):
            await client.call_tool("passport_check", {"passport": _PASSPORT, "group_id": "g-retry"})


async def test_passport_check_refuses_an_existing_case_id() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="already exists"):
            await client.call_tool(
                "passport_check",
                {"passport": _PASSPORT, "group_id": "g-passport", "case_id": "ext-1"},
            )


@pytest.mark.parametrize("days_from_today", [-1, 0])
async def test_passport_check_accepts_a_date_of_birth_up_to_today(days_from_today: int) -> None:
    born = (date.today() + timedelta(days=days_from_today)).isoformat()
    async with Client(_server()) as client:
        result = await client.call_tool(
            "passport_check",
            {"passport": {**_PASSPORT, "date_of_birth": born}, "group_id": "g-passport"},
        )

    assert result.structured_content is not None


async def test_passport_check_refuses_a_future_date_of_birth() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="Date of birth cannot be in the future"):
            await client.call_tool(
                "passport_check",
                {
                    "passport": {**_PASSPORT, "date_of_birth": tomorrow},
                    "group_id": "g-passport",
                },
            )


async def test_passport_check_refuses_a_malformed_case_id() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="String should match pattern"):
            await client.call_tool(
                "passport_check",
                {"passport": _PASSPORT, "group_id": "g-passport", "case_id": "/a"},
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


async def _approve_after_ext_1_moves(
    message: str, _response_type: object, _params: object, _context: object
) -> dict[str, bool]:
    _ext_1_maps_to.append("sys-pass")
    return await _approve(message, _response_type, _params, _context)


async def test_resolve_result_refuses_when_the_case_id_maps_to_another_case_after_approval() -> (
    None
):
    _writes.clear()
    _ext_1_maps_to[:] = ["sys-1"]
    async with Client(_server(), elicitation_handler=_approve_after_ext_1_moves) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "resolve_result",
                {"case": "ext-1", "result_id": "r1", "status": "POSITIVE", "risk": "High"},
            )

    _ext_1_maps_to[:] = ["sys-1"]
    assert _writes == []


async def test_resolve_result_refuses_an_overlapping_approved_write_on_one_case() -> None:
    _writes.clear()
    first_write_arrived = asyncio.Event()
    release_first_write = asyncio.Event()

    async def held_first_write(request: httpx2.Request) -> httpx2.Response:
        if request.method == "PUT":
            first_write_arrived.set()
            await release_first_write.wait()
        return _world_check(request)

    server = build_server(
        fake_upstream_settings(),
        Persistence(store=MemoryStore(), case_locks=InMemoryCaseLocks()),
        httpx2.MockTransport(held_first_write),
    )
    arguments = {"case": "sys-1", "result_id": "r1", "status": "POSITIVE", "risk": "High"}

    async with (
        asyncio.timeout(10),
        Client(server, elicitation_handler=_approve) as first,
        Client(server, elicitation_handler=_approve) as second,
    ):
        first_call = asyncio.create_task(first.call_tool("resolve_result", arguments))
        arrived = asyncio.create_task(first_write_arrived.wait())
        try:
            await asyncio.wait({first_call, arrived}, return_when=asyncio.FIRST_COMPLETED)
            assert first_write_arrived.is_set(), "the first call ended before it wrote"
            with pytest.raises(ToolError, match="Another decision on this case is being saved"):
                await second.call_tool("resolve_result", arguments)
        finally:
            release_first_write.set()
            arrived.cancel()
        await first_call

    assert len(_writes) == 1


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
                {"since": _OGS_SINCE_STAMP, "until": "2999-01-01T00:00:00Z"},
            )


@asynccontextmanager
async def _serve_over_http(server: FastMCP) -> AsyncGenerator[str]:
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = cast(int, reserved.getsockname()[1])
        settings = ServerSettings(
            host="127.0.0.1",
            port=port,
            mcp_base_url=AnyHttpUrl(f"http://127.0.0.1:{port}"),
            mcp_allowed_origins=[],
        )
        config = uvicorn.Config(http_app(server, settings), log_config=None)
        http_server = uvicorn.Server(config)

        async def serve() -> None:
            try:
                await http_server.serve(sockets=[reserved])
            except SystemExit as error:
                raise RuntimeError("the server exited during startup") from error

        serving = asyncio.create_task(serve())
        try:
            async with asyncio.timeout(10):
                while not http_server.started and not serving.done():
                    await asyncio.sleep(0.01)
            assert http_server.started, "the server stopped before it started"
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            http_server.should_exit = True
            await asyncio.gather(serving, return_exceptions=True)


@pytest.mark.parametrize("protocol_version", ["2025-06-18", "2025-11-25"])
async def test_verify_passport_check_saves_after_approval_over_http(
    protocol_version: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _writes.clear()
    monkeypatch.setattr(session, "LATEST_HANDSHAKE_VERSION", protocol_version)
    async with (
        _serve_over_http(_server()) as url,
        Client(url, mode="legacy", elicitation_handler=_approve) as client,
    ):
        assert client.protocol_version == protocol_version
        result = await client.call_tool(
            "verify_passport_check", {"case": "sys-pass", "mrz_matched": True}
        )

    saved = result.structured_content
    assert saved is not None
    assert saved["recorded"] is True
    assert len(_writes) == 1
