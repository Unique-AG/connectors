from collections.abc import Mapping

ONENOTE = "/v1.0/me/onenote"
GROUP = "/v1.0/groups/*/onenote"

READ_TOOLS = frozenset(
    {
        "onenote_list_notebooks",
        "onenote_list_recent_notebooks",
        "onenote_find_notebook_from_url",
        "onenote_list_sections",
        "onenote_list_pages",
        "onenote_preview_page",
        "onenote_read_page",
        "onenote_read_resource",
    }
)
READ_POSTS: Mapping[str, tuple[str, ...]] = {
    "onenote_find_notebook_from_url": (f"POST {ONENOTE}/notebooks/getNotebookFromWebUrl",),
}
READ_GETS: Mapping[str, tuple[str, ...]] = {
    "onenote_list_notebooks": tuple(
        f"GET {GROUP}/{leaf}" for leaf in ("notebooks", "sections", "sectionGroups")
    ),
    "onenote_list_sections": tuple(
        f"GET {GROUP}/{parent}/*/{leaf}"
        for parent in ("notebooks", "sectionGroups")
        for leaf in ("sections", "sectionGroups")
    ),
    "onenote_list_pages": (f"GET {GROUP}/pages", f"GET {GROUP}/sections/*/pages"),
    "onenote_preview_page": (f"GET {GROUP}/pages/*/preview",),
    "onenote_read_page": (f"GET {GROUP}/pages/*/content",),
    "onenote_read_resource": (f"GET {GROUP}/resources/*/content",),
    "onenote_get_operation": (f"GET {GROUP}/operations/*",),
    "onenote_create_page": (f"GET {GROUP}/sections/*", f"GET {GROUP}/notebooks/*"),
    "onenote_copy_section": (f"GET {GROUP}/sections/*",),
    "onenote_copy_page": (f"GET {GROUP}/pages/*",),
}
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "onenote_get_operation": (),
    "onenote_create_notebook": (f"POST {ONENOTE}/notebooks",),
    "onenote_create_section": (
        f"POST {ONENOTE}/notebooks/*/sections",
        f"POST {ONENOTE}/sectionGroups/*/sections",
    ),
    "onenote_create_section_group": (
        f"POST {ONENOTE}/notebooks/*/sectionGroups",
        f"POST {ONENOTE}/sectionGroups/*/sectionGroups",
    ),
    "onenote_create_page": (
        f"POST {ONENOTE}/sections/*/pages",
        f"POST {GROUP}/sections/*/pages",
    ),
    "onenote_append_to_page": (f"POST {ONENOTE}/pages/*/onenotePatchContent",),
    "onenote_edit_page": (f"POST {ONENOTE}/pages/*/onenotePatchContent",),
    "onenote_rename_page": (f"POST {ONENOTE}/pages/*/onenotePatchContent",),
    "onenote_delete_page": (f"DELETE {ONENOTE}/pages/*",),
    "onenote_copy_page": (f"POST {ONENOTE}/pages/*/copyToSection",),
    "onenote_copy_section": (
        f"POST {ONENOTE}/sections/*/copyToNotebook",
        f"POST {ONENOTE}/sections/*/copyToSectionGroup",
    ),
    "onenote_copy_notebook": (f"POST {ONENOTE}/notebooks/*/copyNotebook",),
}
DESTINATIONS = frozenset({"id", "groupId"})
SCHEMA: Mapping[str, str] = {
    "previewText": "text",
    **dict.fromkeys(("createdByAppId", "resourceId"), "id"),
    **dict.fromkeys(
        ("lastAccessedTime", "lastActionDateTime", "createdTime", "lastModifiedTime"), "date"
    ),
    **dict.fromkeys(("userRole", "status", "sourceService"), "enum"),
    **dict.fromkeys(("isDefault", "isShared", "level", "order", "percentComplete"), "number"),
    **dict.fromkeys(
        ("self", "sectionsUrl", "sectionGroupsUrl", "pagesUrl", "contentUrl", "href")
        + ("previewImageUrl", "resourceLocation"),
        "url",
    ),
    **dict.fromkeys(
        ("links", "oneNoteClientUrl", "oneNoteWebUrl", "parentNotebook", "parentSection")
        + ("parentSectionGroup",),
        "object",
    ),
}
GAP_SECONDS = 20
BIG_PAGES = "/me/onenote/pages?$filter=contains(tolower(title),'big page')&$select=id"
SEED_NOTEBOOKS = "/me/onenote/notebooks?$filter=contains(tolower(displayName),'seed-v1')&$select=id"
NEEDS: Mapping[str, str] = {
    "onenote_seed": (
        "Wait until OneNote lists the three seed-v1 notebooks of Mia. A new notebook can take "
        + "some minutes to appear. Then run record_all.sh discover again."
    ),
    "onenote_recent": (
        "Open the notebook seed-v1 Dogfood Notes once in OneNote on the web as Mia. "
        + "Then it enters the recent list."
    ),
    "onenote_group": (
        "Run seed.py apply --phases onenote-group for Mia, after the team exists and its "
        + "SharePoint site is ready. Wait until Graph lists seed-v1 Shared Notes for the team. "
        + "Then run record_all.sh discover again."
    ),
    "onenote_big": (
        "Run seed.py apply --phases onenote-big for Mia. Then run record_all.sh discover again."
    ),
}
PROBES: Mapping[str, tuple[int, str, int]] = {
    "onenote_group": (1, "/me/joinedTeams#seed", 1),
    "onenote_big": (1, BIG_PAGES, 1),
    "onenote_seed": (1, SEED_NOTEBOOKS, 3),
    "onenote_recent": (
        1,
        "/me/onenote/notebooks/getRecentNotebooks(includePersonalNotebooks=true)",
        1,
    ),
}
