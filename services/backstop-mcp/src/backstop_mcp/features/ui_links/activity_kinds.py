"""Activity type → CRM UI page. A type with no row here must not start producing a URL.

Keys cover the row-level `SearchActivitiesRowResponse.type` discriminator, every
`ActivityType` member, and every `EntityActivityType` member. `meeting_call` cannot
choose meetings vs calls, so it is explicitly link-less.
"""

from dataclasses import dataclass
from typing import Final, Literal

from backstop_mcp.features.ui_links.inputs import (
    BackstopLinkTarget,
    CallLinkTarget,
    DocumentLinkTarget,
    EmailLinkTarget,
    MeetingLinkTarget,
    NoteLinkTarget,
)

type ActivityJspSlug = Literal["calls", "meetings", "notes", "documents"]


@dataclass(frozen=True, slots=True)
class ActivityKindMapping:
    """Where one activity-type spelling opens, or None when it must not get a link."""

    slug: ActivityJspSlug | None
    page: Literal["activities.jsp", "email"] | None


ACTIVITY_KINDS: Final[dict[str, ActivityKindMapping]] = {
    "Meeting": ActivityKindMapping(slug="meetings", page="activities.jsp"),
    "Call": ActivityKindMapping(slug="calls", page="activities.jsp"),
    "Note": ActivityKindMapping(slug="notes", page="activities.jsp"),
    "Document": ActivityKindMapping(slug="documents", page="activities.jsp"),
    "Email": ActivityKindMapping(slug=None, page="email"),
    "Email Blast": ActivityKindMapping(slug=None, page="email"),
    "meeting": ActivityKindMapping(slug="meetings", page="activities.jsp"),
    "call": ActivityKindMapping(slug="calls", page="activities.jsp"),
    "note": ActivityKindMapping(slug="notes", page="activities.jsp"),
    "document": ActivityKindMapping(slug="documents", page="activities.jsp"),
    "email": ActivityKindMapping(slug=None, page="email"),
    "email_blast": ActivityKindMapping(slug=None, page="email"),
    "meeting_call": ActivityKindMapping(slug=None, page=None),
}


def _target_kind_to_jsp_slug() -> dict[str, ActivityJspSlug]:
    slugs: dict[str, ActivityJspSlug] = {}
    for name, mapping in ACTIVITY_KINDS.items():
        if mapping.page != "activities.jsp" or mapping.slug is None or not name.islower():
            continue
        slugs[name] = mapping.slug
    return slugs


TARGET_KIND_TO_JSP_SLUG: Final[dict[str, ActivityJspSlug]] = _target_kind_to_jsp_slug()
ACTIVITY_JSP_SLUG_TO_KIND: Final[dict[str, str]] = {
    slug: kind for kind, slug in TARGET_KIND_TO_JSP_SLUG.items()
}

for _name, _mapping in ACTIVITY_KINDS.items():
    if _mapping.page != "activities.jsp":
        continue
    assert _mapping.slug is not None, f"{_name} is activities.jsp but has no slug"
    assert TARGET_KIND_TO_JSP_SLUG[_name.casefold()] == _mapping.slug


def activity_link_target(
    *,
    activity_type: str | None,
    entity_activity_details_id: str,
) -> BackstopLinkTarget | None:
    """Discriminated target for an activity type, or None when that type has no CRM page."""
    if activity_type is None:
        return None
    mapping = ACTIVITY_KINDS.get(activity_type)
    if mapping is None or mapping.page is None:
        return None
    if mapping.page == "email":
        return EmailLinkTarget(entity_activity_details_id=entity_activity_details_id)
    assert mapping.slug is not None, f"{activity_type} is activities.jsp but has no slug"
    match ACTIVITY_JSP_SLUG_TO_KIND[mapping.slug]:
        case "call":
            return CallLinkTarget(entity_activity_details_id=entity_activity_details_id)
        case "meeting":
            return MeetingLinkTarget(entity_activity_details_id=entity_activity_details_id)
        case "note":
            return NoteLinkTarget(entity_activity_details_id=entity_activity_details_id)
        case "document":
            return DocumentLinkTarget(entity_activity_details_id=entity_activity_details_id)
        case _:
            return None
