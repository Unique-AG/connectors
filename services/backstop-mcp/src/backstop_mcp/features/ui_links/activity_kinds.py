"""Activity type → CRM UI page. A type with no row here must not start producing a URL.

Keys cover the row-level `SearchActivitiesRowResponse.type` discriminator, every
`ActivityType` member, and every `EntityActivityType` member. `meeting_call` cannot
choose meetings vs calls, so it is explicitly link-less.
"""

from dataclasses import dataclass
from typing import Final, Literal

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
