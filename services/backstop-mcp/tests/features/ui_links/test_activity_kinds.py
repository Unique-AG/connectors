from typing import cast, get_args

from backstop_mcp.features.activity_history import (
    ENTITY_ACTIVITY_TYPES,
    ActivityType,
    EntityActivityType,
)
from backstop_mcp.features.ui_links import (
    ACTIVITY_JSP_SLUG_TO_KIND,
    ACTIVITY_KINDS,
    TARGET_KIND_TO_JSP_SLUG,
    CallLinkTarget,
    EmailLinkTarget,
    MeetingLinkTarget,
    NoteLinkTarget,
    activity_link_target,
)

_ROW_TYPES = frozenset({"Meeting", "Call", "Email", "Email Blast", "Note", "Document"})


def _literal_strings(annotation: object) -> frozenset[str]:
    origin: object = getattr(annotation, "__value__", annotation)
    args = cast("tuple[object, ...]", get_args(origin))
    values: set[str] = set()
    for arg in args:
        if isinstance(arg, str):
            values.add(arg)
        else:
            values.update(_literal_strings(arg))
    return frozenset(values)


def test_every_activity_type_member_is_mapped_or_explicitly_linkless() -> None:
    activity_types = _literal_strings(ActivityType)
    entity_activity_types = frozenset(ENTITY_ACTIVITY_TYPES)
    assert entity_activity_types == _literal_strings(EntityActivityType)
    assert activity_types
    required = activity_types | entity_activity_types | _ROW_TYPES
    missing = required - frozenset(ACTIVITY_KINDS)
    assert not missing, f"ACTIVITY_KINDS is missing {sorted(missing)}"

    linkless = {name for name, mapping in ACTIVITY_KINDS.items() if mapping.page is None}
    assert "meeting_call" in linkless
    for name, mapping in ACTIVITY_KINDS.items():
        if mapping.page is None:
            assert mapping.slug is None, f"{name} is link-less but has a slug"
        elif mapping.page == "email":
            assert mapping.slug is None, f"{name} is the email page; it is not activities.jsp"
        else:
            assert mapping.page == "activities.jsp"
            assert mapping.slug in {"calls", "meetings", "notes", "documents"}


def test_runtime_jsp_maps_follow_activity_kinds() -> None:
    for kind, slug in TARGET_KIND_TO_JSP_SLUG.items():
        assert ACTIVITY_KINDS[kind].slug == slug
        assert ACTIVITY_KINDS[kind].page == "activities.jsp"
        assert ACTIVITY_JSP_SLUG_TO_KIND[slug] == kind
    assert set(TARGET_KIND_TO_JSP_SLUG) == {"call", "meeting", "note", "document"}


def test_activity_link_target_maps_known_types() -> None:
    assert activity_link_target(
        activity_type="note", entity_activity_details_id="26211573"
    ) == NoteLinkTarget(entity_activity_details_id="26211573")
    assert activity_link_target(
        activity_type="Call", entity_activity_details_id="76777353"
    ) == CallLinkTarget(entity_activity_details_id="76777353")
    assert activity_link_target(
        activity_type="meeting", entity_activity_details_id="76777273"
    ) == MeetingLinkTarget(entity_activity_details_id="76777273")
    assert activity_link_target(
        activity_type="Email Blast", entity_activity_details_id="1804407622"
    ) == EmailLinkTarget(entity_activity_details_id="1804407622")


def test_activity_link_target_is_none_when_kind_has_no_page() -> None:
    assert (
        activity_link_target(activity_type="meeting_call", entity_activity_details_id="1") is None
    )
    assert activity_link_target(activity_type=None, entity_activity_details_id="1") is None
    assert activity_link_target(activity_type="unknown", entity_activity_details_id="1") is None
