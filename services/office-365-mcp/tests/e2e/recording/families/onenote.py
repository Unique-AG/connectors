from collections.abc import Mapping

ONENOTE = "/v1.0/me/onenote"

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
    "onenote_create_page": (f"POST {ONENOTE}/sections/*/pages",),
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
DESTINATIONS = frozenset({"id"})
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
NEEDS: Mapping[str, str] = {
    "onenote_seed": (
        "Wait until OneNote lists the three seed-v1 notebooks of Mia. A new notebook can take "
        + "some minutes to appear. Then run record_all.sh discover again."
    ),
    "onenote_recent": (
        "Open the notebook seed-v1 Dogfood Notes once in OneNote on the web as Mia. "
        + "Then it enters the recent list."
    ),
}
PROBES: Mapping[str, tuple[int, str, int]] = {
    "onenote_seed": (
        1,
        "/me/onenote/notebooks?$filter=contains(tolower(displayName),'seed-v1')&$select=id",
        3,
    ),
    "onenote_recent": (
        1,
        "/me/onenote/notebooks/getRecentNotebooks(includePersonalNotebooks=true)",
        1,
    ),
}
