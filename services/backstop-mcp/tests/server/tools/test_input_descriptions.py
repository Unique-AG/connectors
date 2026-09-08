"""Every argument a tool publishes to the model has a description, and party tools
require `search_type` in wording the model cannot treat as optional.
"""

from collections.abc import Awaitable, Callable
from typing import cast

from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import FunctionTool, ToolMeta

from backstop_mcp.server.tools import TOOLS
from tests.server.tools.helpers import object_dict

_PARTY_TOOLS_REQUIRING_SEARCH_TYPE = frozenset(
    {
        "get_accounts_for_party",
        "get_opportunities",
        "get_tasks_for_party",
    }
)

# Tools the live agent kept calling with invented names. Teach the published call;
# do not accept those aliases.
_TOOLS_WITH_USAGE_SAMPLES = frozenset(
    {
        "get_activity_detail",
        "get_activity_history",
        "get_opportunities",
        "get_organization",
        "get_people_for_party",
        "get_person",
        "get_tasks_for_party",
        "list_activity_tags",
        "list_custom_field_groups",
        "list_custom_fields",
        "search_activities",
        "search_opportunities",
    }
)
_USAGE_SAMPLE_NEEDLES: dict[str, tuple[str, ...]] = {
    "get_activity_detail": ("activity_id",),
    "get_activity_history": ('"request"', '"type": "first"', "groups[type].next"),
    "get_opportunities": ('"search_type"', '"party_id"'),
    "get_organization": ("locations", "primary_contact"),
    "get_people_for_party": ('"search_type"', '"party_id"'),
    "get_person": ("locations", "company"),
    "get_tasks_for_party": ('"search_type"', '"party_id"'),
    "list_activity_tags": ('"search"',),
    "list_custom_field_groups": ("refresh",),
    "list_custom_fields": ("entity_types",),
    "search_activities": ("meeting_call", "party_id", "search_type"),
    "search_opportunities": ("representative", "get_opportunities"),
}


def _published_input_schema(fn: Callable[..., Awaitable[object]]) -> dict[str, object]:
    meta = get_fastmcp_meta(fn)
    assert isinstance(meta, ToolMeta)
    tool = FunctionTool.from_function(fn, metadata=meta)
    return object_dict(cast("object", tool.parameters))


def _collect_input_fields(
    schema: dict[str, object],
    *,
    path: str,
    defs: dict[str, object],
    seen: frozenset[str] = frozenset(),
) -> list[tuple[str, dict[str, object]]]:
    fields: list[tuple[str, dict[str, object]]] = []
    props_raw = schema.get("properties")
    if isinstance(props_raw, dict):
        props = object_dict(cast("object", props_raw))
        for name, raw in props.items():
            field = object_dict(raw)
            child = f"{path}.{name}" if path else name
            fields.append((child, field))
            fields.extend(_collect_input_fields(field, path=child, defs=defs, seen=seen))
    for key in ("anyOf", "oneOf", "allOf"):
        variants_raw = schema.get(key)
        if isinstance(variants_raw, list):
            variants = cast("list[object]", variants_raw)
            for index, raw in enumerate(variants):
                fields.extend(
                    _collect_input_fields(
                        object_dict(raw),
                        path=f"{path}[{key}[{index}]]",
                        defs=defs,
                        seen=seen,
                    )
                )
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        name = ref.rsplit("/", 1)[-1]
        if name not in seen:
            target = defs.get(name)
            if isinstance(target, dict):
                fields.extend(
                    _collect_input_fields(
                        object_dict(cast("object", target)),
                        path=path or name,
                        defs=defs,
                        seen=seen | {name},
                    )
                )
    return fields


def _needs_own_description(field: dict[str, object]) -> bool:
    return "$ref" not in field and not any(key in field for key in ("anyOf", "oneOf", "allOf"))


def test_every_published_input_property_is_described() -> None:
    missing: list[str] = []
    for fn in TOOLS:
        schema = _published_input_schema(fn)
        defs_raw = schema.get("$defs", {})
        defs = object_dict(cast("object", defs_raw)) if isinstance(defs_raw, dict) else {}
        for path, field in _collect_input_fields(schema, path="", defs=defs):
            if _needs_own_description(field) and not field.get("description"):
                missing.append(f"{fn.__name__}.{path}")
    assert missing == []


def test_party_tools_publish_search_type_as_required_and_say_so() -> None:
    for fn in TOOLS:
        if fn.__name__ not in _PARTY_TOOLS_REQUIRING_SEARCH_TYPE:
            continue
        schema = _published_input_schema(fn)
        required = schema.get("required")
        assert isinstance(required, list)
        assert "search_type" in required, fn.__name__
        props = object_dict(schema["properties"])
        search_type = object_dict(props["search_type"])
        party_id = object_dict(props["party_id"])
        search_desc = str(search_type.get("description", ""))
        party_desc = str(party_id.get("description", ""))
        assert "Required" in search_desc or "Never omit" in search_desc
        assert "alone" in party_desc
        doc = fn.__doc__ or ""
        assert "search_type" in doc
        assert "rejected" in doc


def test_confused_tools_publish_a_call_like_sample() -> None:
    missing = [
        fn.__name__
        for fn in TOOLS
        if fn.__name__ in _TOOLS_WITH_USAGE_SAMPLES and "Call like:" not in (fn.__doc__ or "")
    ]
    assert missing == []
    extra = _TOOLS_WITH_USAGE_SAMPLES - {fn.__name__ for fn in TOOLS}
    assert extra == set()
    for fn in TOOLS:
        if fn.__name__ not in _USAGE_SAMPLE_NEEDLES:
            continue
        doc = fn.__doc__ or ""
        for needle in _USAGE_SAMPLE_NEEDLES[fn.__name__]:
            assert needle in doc, f"{fn.__name__} docstring missing {needle!r}"


def test_search_activities_types_name_meeting_call() -> None:
    [fn] = [tool for tool in TOOLS if tool.__name__ == "search_activities"]
    schema = _published_input_schema(fn)
    props = object_dict(schema["properties"])
    types = object_dict(props["types"])
    assert "meeting_call" in str(types.get("description", ""))


def test_activity_history_next_echoes_the_continuation_object() -> None:
    [fn] = [tool for tool in TOOLS if tool.__name__ == "get_activity_history"]
    schema = _published_input_schema(fn)
    defs = object_dict(schema.get("$defs", {}))
    next_page = object_dict(defs["ActivityHistoryNextPageInput"])
    nxt = object_dict(object_dict(next_page["properties"])["next"])
    assert "bare integers" in str(nxt.get("description", ""))


def test_activity_history_first_page_requires_search_type() -> None:
    [fn] = [tool for tool in TOOLS if tool.__name__ == "get_activity_history"]
    schema = _published_input_schema(fn)
    defs = object_dict(schema.get("$defs", {}))
    first_page = object_dict(defs["ActivityHistoryFirstPageInput"])
    required = first_page.get("required")
    assert isinstance(required, list)
    assert "search_type" in required
    search_type = object_dict(object_dict(first_page["properties"])["search_type"])
    party_id = object_dict(object_dict(first_page["properties"])["party_id"])
    assert "Never omit" in str(search_type.get("description", ""))
    assert "alone" in str(party_id.get("description", ""))
    assert "rejected" in (fn.__doc__ or "")
