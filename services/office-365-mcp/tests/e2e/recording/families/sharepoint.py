from collections.abc import Mapping

READ_TOOLS = frozenset(
    {
        "get_me",
        "sharepoint_browse_folder",
        "sharepoint_list_drives",
        "sharepoint_read_file",
        "sharepoint_resolve_url",
        "sharepoint_search_files",
        "sharepoint_search_sites",
    }
)
READ_POSTS: Mapping[str, tuple[str, ...]] = {
    "sharepoint_search_files": ("POST /v1.0/search/query",),
}
READ_GETS: Mapping[str, tuple[str, ...]] = {
    "sharepoint_resolve_url": ("GET /v1.0/shares/u!*/driveItem",),
    "sharepoint_search_sites": ("GET /v1.0/sites",),
}
_ITEM = "/v1.0/drives/b!*/items/*"
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "sharepoint_rename_item": (f"PATCH {_ITEM}",),
    "sharepoint_move_item": (f"PATCH {_ITEM}",),
    "sharepoint_delete_item": (f"DELETE {_ITEM}",),
    "sharepoint_create_share_link": (f"POST {_ITEM}/createLink",),
    "sharepoint_create_folder": (f"POST {_ITEM}/children",),
    "sharepoint_copy_item": (f"POST {_ITEM}/copy",),
    "sharepoint_invite": (f"POST {_ITEM}/invite",),
    "sharepoint_create_text_file": ("PUT /v1.0/drives/b!*/items/*:/seed-v1?case-*:/content",),
}
CREATED_ONLY: Mapping[str, int] = {"sharepoint_invite": 0}
EXTERNAL = frozenset({"sharepoint_create_share_link", "sharepoint_invite"})
DESTINATIONS = frozenset({"parentReference.id"})
FORBIDDEN: Mapping[str, frozenset[str]] = {"scope": frozenset({"anonymous"})}
SCHEMA: Mapping[str, str] = {
    "givenName": "text",
    "surname": "text",
    "jobTitle": "text",
    "officeLocation": "text",
    "businessPhones": "text",
    "mobilePhone": "text",
    "preferredLanguage": "enum",
    "mail": "address",
    "userPrincipalName": "address",
    "webDavUrl": "url",
    "owner": "object",
    "root": "object",
    "link": "object",
    "invitation": "object",
    "grantedTo": "object",
    "grantedToV2": "object",
    "signInRequired": "number",
    "type": "enum",
    "scope": "enum",
}
NEEDS: Mapping[str, str] = {
    "sharepoint-seed-files": (
        "Run seed.py apply --as 1 for the first test user. Then wait one hour. Microsoft Search "
        + "must index the new files and the folder."
    ),
}
PROBES: Mapping[str, tuple[int, str, int]] = {
    "sharepoint-seed-files": (1, "/me/drive/root:/seed-v1 Seed Files:/children", 4),
}
