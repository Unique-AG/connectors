"""Builds `src/polixis_mcp/upstream/openapi.yml` from Polixis's own spec beside this file.

Polixis's spec is the source of truth. Every change made to it is one `Edit` in a section below,
saying what it changes and why, so the sections are the full record of what we added or
corrected. Run it, then the codegen, when Polixis sends a new spec:

    uv run poe merge-spec && uv run poe codegen
"""

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import TypeAdapter
import yaml

type Json = dict[str, Json] | list[Json] | str | int | float | bool | None
type JsonObject = dict[str, Json]

_HERE = Path(__file__).parent
VENDOR = _HERE / "polixis-graph.openapi.json"
OUT = _HERE.parent / "src/polixis_mcp/upstream/openapi.yml"

OPERATION_IDS = {
    ("/api/basic-identifiers/{id}", "get"): "getBasicIdentifiers",
    ("/api/completion/fields", "get"): "listCompletionFields",
    ("/api/completion/{id}", "post"): "getProfileFields",
    ("/api/corporate/byPublisher", "post"): "getCorporateProfile",
    ("/api/graph/pid/{pid}", "get"): "resolvePermanentId",
    ("/api/graph/smart", "post"): "getSmartGraph",
    ("/api/graph/subgraph", "post"): "getSubgraph",
    ("/api/graph/topdown/{id}", "get"): "getTopDownOwnership",
    ("/api/graph/ubo/{id}", "get"): "getUltimateBeneficialOwners",
    ("/api/key-identifiers/{id}", "get"): "getKeyIdentifiers",
}

UNDOCUMENTED = (
    "Not in Polixis's spec. It answered live on 2026-11-09; whether Polixis supports it is an "
    "open question to them, so the tools that call it say it may change."
)


class Edit(BaseModel):
    """One change to Polixis's spec at `at`, a path of keys. `set` puts `value` there, adding it
    when missing; `append` adds `value` to the end of the string there; `update` adds the keys
    of `value` to the object there; `extend` adds the items of `value` to the list there.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    at: tuple[str, ...]
    kind: Literal["set", "append", "update", "extend"]
    value: Json


def set_(*at: str, value: Json) -> Edit:
    return Edit(at=at, kind="set", value=value)


def append(*at: str, value: str) -> Edit:
    return Edit(at=at, kind="append", value=value)


def update(*at: str, value: JsonObject) -> Edit:
    return Edit(at=at, kind="update", value=value)


def extend(*at: str, value: list[Json]) -> Edit:
    return Edit(at=at, kind="extend", value=value)


def ref(name: str) -> JsonObject:
    return {"$ref": f"#/components/schemas/{name}"}


def array(items: Json) -> JsonObject:
    return {"type": "array", "items": items}


def string_map(values: Json) -> JsonObject:
    return {"type": "object", "additionalProperties": values}


STRING: JsonObject = {"type": "string"}
STRING_LIST_MAP = string_map(array(STRING))
REJECTION_FIELDS: JsonObject = {"error": ref("RejectionMessage"), "code": ref("RejectionCode")}


def json_body(schema: Json, description: str) -> JsonObject:
    return {"description": description, "content": {"application/json": {"schema": schema}}}


def request_body(schema: Json) -> JsonObject:
    return {"required": True, "content": {"application/json": {"schema": schema}}}


def schema(name: str, *at: str) -> tuple[str, ...]:
    return ("components", "schemas", name, *at)


def operation(path: str, method: str, *at: str) -> tuple[str, ...]:
    return ("paths", path, method, *at)


def merge(vendor: JsonObject) -> JsonObject:
    edits = [
        *_service(),
        *_operation_ids(),
        *_rejections(),
        *_timestamps(),
        *_corporate(vendor),
        *_graph(),
        *_completion(),
        *_names(),
        *_permanent_id(),
        *_search(),
        *_undocumented(),
    ]
    merged = _with_edits(_wrap_annotated_refs(vendor), edits)
    assert isinstance(merged, dict)
    return merged


def _applied(node: Json, edit: Edit) -> Json:
    """`node` with `edit` made. Every object on the way is copied, so neither `node` nor
    Polixis's spec changes.
    """
    return _applied_below(node, at=edit.at, edit=edit)


def _applied_below(node: Json, *, at: tuple[str, ...], edit: Edit) -> Json:
    if at:
        assert isinstance(node, dict | None), f"{edit.at}: {at[0]} is not inside an object"
        current = node or {}
        return {**current, at[0]: _applied_below(current.get(at[0]), at=at[1:], edit=edit)}
    match edit.kind, node, edit.value:
        case "set", _, value:
            return value
        case "append", str(text), str(suffix):
            return text + suffix
        case "update", dict(current), dict(added):
            return {**current, **added}
        case "extend", list(items), list(added):
            return [*items, *added]
        case _:
            raise AssertionError(f"{edit.at}: cannot {edit.kind} {type(node).__name__}")


def _wrap_annotated_refs(node: Json) -> Json:
    """Moves a $ref with siblings into allOf. OpenAPI 3.0 ignores a $ref's siblings, and our
    codegen does not follow such a ref, so the vendor's descriptions there would be lost.
    """
    if isinstance(node, list):
        return [_wrap_annotated_refs(item) for item in node]
    if not isinstance(node, dict):
        return node
    return {key: _wrapped(value) for key, value in node.items()}


def _wrapped(value: Json) -> Json:
    if isinstance(value, dict) and "$ref" in value and len(value) > 1:
        annotations = {k: v for k, v in value.items() if k not in ("$ref", "type")}
        return {"allOf": [{"$ref": value["$ref"]}], **annotations}
    return _wrap_annotated_refs(value)


def _service() -> list[Edit]:
    return [
        # Our codegen reads OpenAPI 3.0 only, and Polixis's 3.1 file uses nothing 3.0 lacks.
        set_("openapi", value="3.0.3"),
        set_(
            "info",
            "description",
            value=(
                "Polixis's own spec for the graph service (the source of truth, in "
                "spec/polixis-graph.openapi.json), merged with what the live API showed in "
                "November 2026 by spec/merge_spec.py. Declared 3.0.3 for our codegen; Polixis's "
                "file says 3.1.0 but uses nothing 3.0 lacks. Additions: operationIds, the search "
                "service, the rejection body, typed completion and node metadata, and the routes "
                "Polixis does not document (tag Undocumented). Corrections, each noted where it "
                "is made: timestamps are epoch seconds, not milliseconds, and the server needs no "
                "/graph prefix."
            ),
        ),
        set_(
            "servers",
            value=[
                {
                    "url": "https://api-polixis.polixis.com",
                    "description": (
                        "Polixis's spec gives /graph, but the API answers without that prefix."
                    ),
                }
            ],
        ),
        set_("security", value=[{"clientCredentials": [], "apiKey": []}]),
        set_(
            "components",
            "securitySchemes",
            value={
                "clientCredentials": {
                    "type": "oauth2",
                    "flows": {
                        "clientCredentials": {
                            "tokenUrl": (
                                "https://auth.polixis.com/realms/plx-prod/protocol/openid-connect/token"
                            ),
                            "scopes": {},
                        }
                    },
                },
                "apiKey": {"type": "apiKey", "in": "header", "name": "x-api-key"},
            },
        ),
        extend(
            "tags",
            value=[
                {
                    "name": "Search",
                    "description": "Name and identifier search, a service separate from the graph.",
                },
                {"name": "Undocumented", "description": UNDOCUMENTED},
            ],
        ),
    ]


def _operation_ids() -> list[Edit]:
    """Polixis's spec has none, and the codegen names each operation after its id."""
    return [
        set_(*operation(path, method, "operationId"), value=operation_id)
        for (path, method), operation_id in OPERATION_IDS.items()
    ]


def _rejections() -> list[Edit]:
    rejected = (
        "BasicIdentifiersResponse",
        "KeyIdentifiersResponse",
        "CorporateProfileResponse",
        "CorporateProfilesResponse",
        "SmartGraphResponse",
        "VirtualSubgraph",
        "UboResult",
    )
    return [
        set_(
            *schema("RejectionMessage"),
            value={
                "type": "string",
                "description": (
                    "Why Polixis rejected the request, sent with a 200 in place of the body."
                ),
            },
        ),
        set_(
            *schema("RejectionCode"),
            value={
                "type": "string",
                "description": (
                    "The kind of rejection, such as VALIDATION for an id Polixis does not know."
                ),
            },
        ),
        *(update(*schema(name, "properties"), value=REJECTION_FIELDS) for name in rejected),
        append(
            *operation("/api/graph/smart", "post", "description"),
            value=(
                " An id Polixis does not know gets a 200 with `error` and `code` (VALIDATION) in "
                "place of the body, here and on every endpoint that takes an id."
            ),
        ),
    ]


def _timestamps() -> list[Edit]:
    return [
        *(
            set_(
                *schema("ConnectionDetail", "properties", field, "description"),
                value=(
                    f"{meaning}, in epoch seconds. Polixis's spec says milliseconds, but every "
                    "value the live API returned is in seconds (1778803200 is 2026-05-15)."
                ),
            )
            for field, meaning in [
                ("at", "The time the information refers to"),
                ("startDate", "The start of the relation"),
                ("endDate", "The end of the relation"),
            ]
        ),
        append(
            *schema("VirtualEdge", "description"),
            value=" The source holds each detail's role in the target, such as being its "
            "shareholder.",
        ),
    ]


def _corporate(vendor: JsonObject) -> list[Edit]:
    corporate = operation("/api/corporate/byPublisher", "post")
    return [
        set_(*corporate, "parameters", value=_required_page(_at(vendor, *corporate, "parameters"))),
        set_(
            *corporate,
            *("responses", "200", "content", "application/json", "schema"),
            value=ref("CorporateProfileResponse"),
        ),
        append(*corporate, "description", value=" A request without `category` fails with a 500."),
        set_(*schema("CorporateRequest", "required"), value=["id", "category"]),
        append(
            *schema("CorporateRequest", "properties", "category", "description"),
            value=" Required: Polixis answers a 500 without it.",
        ),
        set_(
            *schema("RelationGroup", "properties", "type", "description"),
            value=(
                "The relation category. Polixis's spec says a CorporateCategory value, but the "
                "live API sends its own names, such as shareholding_ownership, "
                "shareholding_ownership_reverse or executive."
            ),
        ),
        append(
            *schema("EntityData", "properties", "flags", "description"),
            value=' Live, one object per flag keyed by its name: {"SANCTION": {"value": '
            '"#SANCTION"}}.',
        ),
    ]


def _required_page(parameters: Json) -> Json:
    """The corporate profile's parameters with `page` required: the tools use the flat page."""
    assert isinstance(parameters, list)
    edits = [
        set_("required", value=True),
        append(
            "description",
            value=" Required here: the tools use the flat page. Without it the response is a "
            "CorporateProfilesResponse instead.",
        ),
        set_("schema", "minimum", value=0),
    ]
    return [
        _with_edits(parameter, edits)
        if isinstance(parameter, dict) and parameter.get("name") == "page"
        else parameter
        for parameter in parameters
    ]


def _with_edits(node: Json, edits: list[Edit]) -> Json:
    for edit in edits:
        node = _applied(node, edit)
    return node


def _at(node: Json, *at: str) -> Json:
    for key in at:
        assert isinstance(node, dict), f"{at}: {key} is not inside an object"
        node = node[key]
    return node


def _graph() -> list[Edit]:
    capped = " Capped at 300 nodes per level and 5,000 per request; `truncated` says a cap was hit."
    return [
        set_(
            *schema("NodeMeta"),
            value={
                "type": "object",
                "description": "What Polixis returns about one node besides the node itself.",
                "properties": {
                    "names": {
                        **STRING_LIST_MAP,
                        "description": "Its names, keyed by original and en.",
                    },
                    "images": {**array(STRING), "description": "Image URLs."},
                },
            },
        ),
        set_(
            *schema("NodeMetaMap"),
            value={
                **string_map(ref("NodeMeta")),
                "description": (
                    "Metadata of each node, keyed by its pid. The smart graph and the ownership "
                    "trees always send names and images. The subgraph sends only the `fields` "
                    "requested, and no names even then."
                ),
            },
        ),
        *(
            set_(*schema(name, "properties", "meta"), value=ref("NodeMetaMap"))
            for name in ("SmartGraphResponse", "UboResult", "VirtualSubgraph")
        ),
        append(
            *schema("VirtualNode", "properties", "alertNames", "description"),
            value=" Live, the node's own alert categories in upper case, such as STATECO or "
            "RESTRICTION.",
        ),
        append(
            *schema("VirtualNode", "properties", "flags", "description"),
            value=" Sent without a leading #.",
        ),
        *(
            append(
                *schema("RadiusFilter", "properties", name, "description"),
                value=" The encoding behind string/binary is unconfirmed: a list of ctg codes, "
                "as bytes.",
            )
            for name in ("allowedCtg", "excludedCtg")
        ),
        append(
            *schema("UboNode", "properties", "sharePercent", "description"),
            value=" 0 when not reported.",
        ),
        append(
            *schema("UboResult", "properties", "totalNodes", "description"),
            value=" Counts every level, an entity reached twice included.",
        ),
        append(*operation("/api/graph/topdown/{id}", "get", "description"), value=capped),
        append(*operation("/api/graph/ubo/{id}", "get", "description"), value=capped),
        append(
            *operation("/api/graph/smart", "post", "description"),
            value=" Leaves out signatory, third-party and historic relations.",
        ),
    ]


def _completion() -> list[Edit]:
    """Polixis's spec leaves the completion response a free-form object."""
    return [
        set_(
            *schema("SanctionRecord"),
            value={
                "type": "object",
                "description": "One listing on a sanctions list.",
                "properties": {"country": STRING, "details": STRING_LIST_MAP},
            },
        ),
        set_(
            *schema("Position"),
            value={
                "type": "object",
                "description": "A position held by a politically exposed person.",
                "properties": {
                    "position": STRING,
                    "institution": STRING,
                    "startDate": ref("DateEntry"),
                    "endDate": ref("DateEntry"),
                    "remark": STRING,
                },
            },
        ),
        set_(
            *schema("Profile"),
            value={
                "type": "object",
                "description": (
                    "The fields a completion request named, typed from live responses: "
                    "Polixis's spec leaves this a free-form object."
                ),
                "properties": {
                    "names": STRING_LIST_MAP,
                    "nameRecords": array(ref("NameRecord")),
                    "legalTypeEntries": array(ref("LegalTypeEntry")),
                    "countries": STRING_LIST_MAP,
                    "unis": STRING_LIST_MAP,
                    "dates": string_map(array(ref("DateEntry"))),
                    "gender": STRING,
                    "flags": array(STRING),
                    "alertList": array(ref("Alert")),
                    "addresses": array(STRING),
                    "eacEntries": array(ref("EacEntry")),
                    "sanctionStatuses": string_map(STRING),
                    "sanctions": {
                        **string_map(array(ref("SanctionRecord"))),
                        "description": "Sanction records per sanctions list.",
                    },
                    "positions": array(ref("Position")),
                    **REJECTION_FIELDS,
                },
            },
        ),
        set_(
            *operation("/api/completion/{id}", "post"),
            *("responses", "200", "content", "application/json", "schema"),
            value=ref("Profile"),
        ),
        set_(*schema("CompletionRequest", "required"), value=["fields"]),
    ]


def _names() -> list[Edit]:
    return [
        set_(
            *schema("NameRecord", "properties", "type", "description"),
            value="The kind of name. Live values: CURRENT_NAME, FORMER_NAME, TRADE_NAME, ALIAS.",
        )
    ]


def _permanent_id() -> list[Edit]:
    responses = operation("/api/graph/pid/{pid}", "get", "responses")
    return [
        # Served as a tool straight from the spec, so this is what the agent reads. Theirs
        # describes the HTTP answers, not when to call it.
        set_(
            *operation("/api/graph/pid/{pid}", "get", "description"),
            value=(
                "Checks a pid the user already holds, such as one stored in a client file. Call "
                "it first whenever the user gives a pid rather than a name. `status` is `active` "
                "when the pid is current: use it as it is. It is `merged` when Polixis merged "
                "the entity into another, whose pid is `redir`: use that one, and tell the user "
                "to update their records. It is `never minted` when Polixis does not know the "
                "pid: say so, describe no entity, and find the client again by name or "
                "identifier. A 410 error means the pid named a group Polixis dissolved, and "
                "lists its former members."
            ),
        ),
        # The pattern tells the agent what a pid looks like. FastMCP does not check a tool
        # served from the spec against it, so a malformed pid still reaches Polixis, which
        # answers 400.
        set_(
            *operation("/api/graph/pid/{pid}", "get", "parameters"),
            value=[
                {
                    "name": "pid",
                    "in": "path",
                    "required": True,
                    "description": "The pid to check: P, O or U, then 32 hex digits.",
                    "schema": {"type": "string", "pattern": "^[POUpou][0-9a-fA-F]{32}$"},
                }
            ],
        ),
        set_(
            *schema("PidMembers", "properties", "status", "description"),
            value="active, merged, or never minted.",
        ),
        update(
            *schema("PidMembers", "properties", "redir"),
            value={"nullable": True, "description": "The pid a merged pid now points to."},
        ),
        set_(
            *schema("PidMembers", "properties", "count", "description"),
            value="The number of members.",
        ),
        set_(
            *schema("PidMembers", "properties", "members", "description"),
            value="The member record ids.",
        ),
        set_(*responses, "400", value={"description": "Not a pid shape."}),
        set_(
            *responses,
            "410",
            value={
                "description": "A dissolved group, with a `references` list of its former members."
            },
        ),
        set_(
            *responses,
            "500",
            value={
                "description": "Seen live for some unknown pids, which the spec says get a 200."
            },
        ),
    ]


def _search() -> list[Edit]:
    """The search service is not in Polixis's spec, which covers only the graph service."""
    unconfirmed = "Accepted live; its effect is unconfirmed."
    return [
        set_(
            "paths",
            "/search/api",
            value={
                "post": {
                    "operationId": "searchEntities",
                    "tags": ["Search"],
                    "summary": "Search organizations and people by name or identifier",
                    "description": (
                        "Finds profiles by name, registration number or ISIN, optionally narrowed "
                        "by entity type, countries and dates. Exact matches rank first, then fuzzy "
                        "ones. Use the returned `pid` with the other endpoints. Not in Polixis's "
                        "spec, which covers only the graph service: written from their PDF and "
                        "live responses."
                    ),
                    "requestBody": request_body(ref("SearchRequest")),
                    "responses": {
                        "200": json_body(
                            ref("SearchResponse"), "Matching profiles, one page of them."
                        ),
                        "400": {
                            "description": (
                                "An unknown field (\"unknown field 'X'\"), a name with no token "
                                "long enough, or a page below 1."
                            )
                        },
                    },
                }
            },
        ),
        set_(
            *schema("SearchRequest"),
            value={
                "type": "object",
                "additionalProperties": False,
                "required": ["name"],
                "properties": {
                    "name": {**STRING, "description": "A name, unique identifier or ISIN."},
                    "entityType": {**STRING, "enum": ["ORGANIZATION", "PERSON"]},
                    "countries": {
                        **array(STRING),
                        "description": (
                            "Lowercase ISO 3166-1 alpha-2 codes; a hit matches at least one."
                        ),
                    },
                    "dates": {
                        **array({"type": "integer"}),
                        "description": (
                            "Dates as yyyyMMdd integers, with 00 for an unknown month or day "
                            "(19780200 is February 1978, 19780000 the year 1978). A hit matches "
                            "when one of its dates falls within one."
                        ),
                    },
                    "adaptiveLegalForms": {
                        "type": "boolean",
                        "description": (
                            "Also match translations and variants of legal forms in names. On by "
                            "default; off cut one search from 1,010 hits to 153."
                        ),
                    },
                    "sanction": {"type": "boolean", "description": unconfirmed},
                    "pep": {"type": "boolean", "description": unconfirmed},
                    "formerPep": {"type": "boolean", "description": unconfirmed},
                    "unis": {
                        **array(STRING),
                        "description": (
                            "Identifier strings. Accepted live and narrows the hits (1,010 to "
                            "113 in one search), but what it matches is unconfirmed."
                        ),
                    },
                    "size": {"type": "integer", "minimum": 1, "maximum": 50},
                    "page": {"type": "integer", "minimum": 1},
                },
            },
        ),
        set_(
            *schema("SearchResponse"),
            value={
                "type": "object",
                "properties": {"hits": array(ref("SearchHit")), "pagination": ref("Pagination")},
            },
        ),
        set_(
            *schema("SearchHit"),
            value={
                "type": "object",
                "properties": {
                    "pid": STRING,
                    "entityType": STRING,
                    "names": array(STRING),
                    "sanction": {"type": "boolean"},
                    "pep": {"type": "boolean"},
                    "alerts": array(ref("AlertEntry")),
                    "nameRecords": array(ref("NameRecord")),
                    "dates": string_map(array(ref("DateEntry"))),
                    "unis": STRING_LIST_MAP,
                    "sanctionStatuses": string_map(STRING),
                    "countries": array(STRING),
                    "addresses": array(STRING),
                },
            },
        ),
        set_(
            *schema("Pagination"),
            value={
                "type": "object",
                "properties": {
                    "page": {"type": "integer"},
                    "size": {"type": "integer"},
                    "totalHits": {"type": "integer"},
                    "hasNext": {"type": "boolean"},
                },
            },
        ),
    ]


def _undocumented() -> list[Edit]:
    """Routes the live API answers that Polixis's spec leaves out, typed from live responses."""
    entity_id: JsonObject = {
        "name": "id",
        "in": "path",
        "required": True,
        "schema": STRING,
        "description": "Entity identifier (resolved to an internal node id).",
    }
    return [
        set_(
            "paths",
            "/api/sanction/{id}",
            value={
                "get": {
                    "operationId": "getSanctionExposure",
                    "tags": ["Undocumented"],
                    "summary": "An entity's sanctions and the sanctioned parties related to it",
                    "description": f"{UNDOCUMENTED} Two calls on the same entity returned 85, "
                    "then 139 related parties.",
                    "parameters": [entity_id],
                    "responses": {
                        "200": json_body(ref("SanctionExposure"), "Direct and related sanctions.")
                    },
                }
            },
        ),
        set_(
            "paths",
            "/api/graph/path",
            value={
                "post": {
                    "operationId": "findPaths",
                    "tags": ["Undocumented"],
                    "summary": "Paths between two entities",
                    "description": f"{UNDOCUMENTED} Every extra request field tried was ignored.",
                    "requestBody": request_body(ref("PathRequest")),
                    "responses": {"200": json_body(ref("PathResponse"), "The paths found.")},
                }
            },
        ),
        set_(
            "paths",
            "/api/judicial/{id}",
            value={
                "get": {
                    "operationId": "getJudicialRecords",
                    "tags": ["Undocumented"],
                    "summary": "Court decisions naming an entity or its related parties",
                    "description": f"{UNDOCUMENTED} Any id, an invalid one included, gets `{{}}` "
                    "when there is nothing.",
                    "parameters": [entity_id],
                    "responses": {
                        "200": json_body(ref("JudicialRecords"), "Court decisions by country.")
                    },
                }
            },
        ),
        set_(
            "paths",
            "/api/search",
            value={
                "post": {
                    "operationId": "searchRecords",
                    "tags": ["Undocumented"],
                    "summary": "Keyword search over source records",
                    "description": f"{UNDOCUMENTED} Returns source records with ARDIS ids, not "
                    "pids.",
                    "requestBody": request_body(ref("RecordSearchRequest")),
                    "responses": {
                        "200": json_body(ref("RecordSearchResponse"), "Matching records.")
                    },
                }
            },
        ),
        set_(
            *schema("SanctionExposure"),
            value={
                "type": "object",
                "properties": {
                    "directSanctions": array(ref("SanctionRecord")),
                    "relatedSanctions": array(ref("SanctionedParty")),
                    **REJECTION_FIELDS,
                },
            },
        ),
        set_(
            *schema("SanctionedParty"),
            value={
                "type": "object",
                "properties": {
                    "pid": STRING,
                    "nameEn": STRING,
                    "unis": STRING_LIST_MAP,
                    "dates": string_map(array(ref("DateEntry"))),
                    "countries": STRING_LIST_MAP,
                    "sanctions": {
                        **string_map(array(ref("SanctionRecord"))),
                        "description": "Sanction records per sanctions list.",
                    },
                    "relationPaths": {
                        **array(ref("SanctionPathHop")),
                        "description": "The hops from the requested entity to this party.",
                    },
                    "images": array(STRING),
                },
            },
        ),
        set_(
            *schema("SanctionPathHop"),
            value={
                "type": "object",
                "properties": {
                    "connection": ref("ConnectionDetail"),
                    "sourceName": STRING,
                    "targetName": STRING,
                },
            },
        ),
        set_(
            *schema("PathRequest"),
            value={
                "type": "object",
                "required": ["sourceId", "targetId"],
                "properties": {"sourceId": STRING, "targetId": STRING},
            },
        ),
        set_(
            *schema("PathResponse"),
            value={
                "type": "object",
                "properties": {
                    "paths": array(ref("GraphPath")),
                    "meta": ref("NodeMetaMap"),
                    **REJECTION_FIELDS,
                },
            },
        ),
        set_(
            *schema("GraphPath"),
            value={
                "type": "object",
                "description": "One path; a composite node may appear more than once.",
                "properties": {
                    "nodes": array(ref("VirtualNode")),
                    "edges": array(ref("VirtualEdge")),
                },
            },
        ),
        set_(
            *schema("JudicialRecords"),
            value={
                "type": "object",
                "properties": {
                    "rootJudicialDetails": {
                        **string_map(array(ref("JudicialRecord"))),
                        "description": (
                            "Decisions naming the entity, keyed by country code (case varies)."
                        ),
                    },
                    "relatedJudicialDetails": {
                        **string_map(array(ref("JudicialRecord"))),
                        "description": (
                            "Decisions naming its related parties, keyed by country code."
                        ),
                    },
                },
            },
        ),
        set_(
            *schema("JudicialRecord"),
            value={
                "type": "object",
                "properties": {
                    "id": STRING,
                    "courtType": STRING,
                    "country": STRING,
                    "year": STRING,
                    "snippet": array(STRING),
                    "content": {
                        **STRING,
                        "description": "The full decision text, up to about 62 KB.",
                    },
                },
            },
        ),
        set_(
            *schema("RecordSearchRequest"),
            value={
                "type": "object",
                "required": ["keyword", "type"],
                "properties": {
                    "keyword": STRING,
                    "type": {**STRING, "enum": ["organization", "person"]},
                    "match": {**STRING, "enum": ["exact", "fuzzy"]},
                },
            },
        ),
        set_(
            *schema("RecordSearchResponse"),
            value={
                "type": "object",
                "properties": {"results": array(ref("SourceRecord")), "messages": array(STRING)},
            },
        ),
        set_(
            *schema("SourceRecord"),
            value={
                "type": "object",
                "properties": {
                    "ardisId": STRING,
                    "nameEn": STRING,
                    "nameOriginal": STRING,
                    "type": STRING,
                    "names": array(STRING),
                    "alerts": array(STRING),
                    "addresses": array(STRING),
                    "countries": array(STRING),
                    "uni": STRING_LIST_MAP,
                    "dates": {
                        **STRING_LIST_MAP,
                        "description": "Dates as DD/MON/YYYY strings, by kind.",
                    },
                    "metadata": array(ref("SourceRecordMetadata")),
                    "gender": STRING,
                    "avatar": STRING,
                },
            },
        ),
        set_(
            *schema("SourceRecordMetadata"),
            value={
                "type": "object",
                "properties": {"id": STRING, "source": array(STRING), "names": array(STRING)},
            },
        ),
    ]


class _Dumper(yaml.SafeDumper):
    """Folds a long string, so a description reads as a paragraph in the YAML."""


def _string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = ">" if len(value) > 90 else None
    # PyYAML ships no types, so its value parameter is unknown to the type check.
    return dumper.represent_scalar(  # pyright: ignore[reportUnknownMemberType]
        "tag:yaml.org,2002:str", value, style=style
    )


_Dumper.add_representer(str, _string)

_SPEC = TypeAdapter[JsonObject](dict[str, Json])
_SECTIONS = ("openapi", "info", "servers", "security", "tags", "paths", "components")


def main() -> None:
    spec = merge(_SPEC.validate_json(VENDOR.read_bytes()))
    ordered = {key: spec[key] for key in _SECTIONS}
    OUT.write_text(
        yaml.dump(ordered, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
    )


if __name__ == "__main__":
    main()
