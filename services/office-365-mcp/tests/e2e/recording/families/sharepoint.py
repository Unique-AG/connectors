from collections.abc import Mapping

READ_TOOLS = frozenset(
    {
        "get_me",
        "sharepoint_browse_folder",
        "sharepoint_get_list",
        "sharepoint_list_drives",
        "sharepoint_list_items",
        "sharepoint_list_lists",
        "sharepoint_read_file",
        "sharepoint_resolve_url",
        "sharepoint_search_files",
        "sharepoint_search_sites",
    }
)
READ_POSTS: Mapping[str, tuple[str, ...]] = {
    "sharepoint_search_files": ("POST /v1.0/search/query",),
}
_ITEM = "/v1.0/drives/b!*/items/*"
_LIST = "/v1.0/sites/?*,*,*/lists/*"  # "?*" keeps the site id out of the seed targets
READ_GETS: Mapping[str, tuple[str, ...]] = {
    "sharepoint_resolve_url": ("GET /v1.0/shares/u!*/driveItem",),
    "sharepoint_list_drives": (
        "GET /v1.0/sites/*/sites/*/drives",
        "GET /v1.0/sites/*/teams/*/drives",
        "GET /v1.0/sites/*/drives",
    ),
    "sharepoint_search_sites": ("GET /v1.0/sites",),
    "sharepoint_list_lists": (
        "GET /v1.0/sites/*.sharepoint.com",
        "GET /v1.0/sites/*.sharepoint.com:/sites/*",
        "GET /v1.0/sites/*.sharepoint.com:/teams/*",
        "GET /v1.0/sites/*,*,*/lists",
    ),
    "sharepoint_get_list": (f"GET {_LIST}/columns",),
    "sharepoint_list_items": (f"GET {_LIST}/columns", f"GET {_LIST}/items"),
    "sharepoint_create_list_item": (f"GET {_LIST}", f"GET {_LIST}/columns"),
    "sharepoint_update_list_item": (f"GET {_LIST}", f"GET {_LIST}/columns", f"GET {_LIST}/items/*"),
    "sharepoint_delete_list_item": (f"GET {_LIST}", f"GET {_LIST}/items/*"),
    "sharepoint_browse_folder": (f"GET {_ITEM}/children",),
    "sharepoint_create_folder": (f"GET {_ITEM}",),
    "sharepoint_copy_item": (f"GET {_ITEM}",),
}
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "sharepoint_rename_item": (f"PATCH {_ITEM}",),
    "sharepoint_move_item": (f"PATCH {_ITEM}",),
    "sharepoint_delete_item": (f"DELETE {_ITEM}",),
    "sharepoint_create_share_link": (f"POST {_ITEM}/createLink",),
    "sharepoint_create_folder": (f"POST {_ITEM}/children",),
    "sharepoint_copy_item": (f"POST {_ITEM}/copy",),
    "sharepoint_invite": (f"POST {_ITEM}/invite",),
    "sharepoint_create_text_file": ("PUT /v1.0/drives/b!*/items/*:/seed-v1?case-*:/content",),
    "sharepoint_create_list_item": (f"POST {_LIST}/items",),
    "sharepoint_update_list_item": (f"PATCH {_LIST}/items/*/fields",),
    "sharepoint_delete_list_item": (f"DELETE {_LIST}/items/*",),
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
SEED_FOLDER = "/me/drive/root:/seed-v1 Seed Files"
NEEDS: Mapping[str, str] = {
    "sharepoint-seed-files": (
        "Run seed.py apply --as 1 for the first test user. Then wait one hour. Microsoft Search "
        + "must index the new files and the folder."
    ),
    "sharepoint-tree": (
        "Run seed.py apply --phases files-tree for Mia, then for Anna. Then wait one hour. "
        + "Microsoft Search must index the folders and the files."
    ),
    "sharepoint-big-files": (
        "Run seed.py apply --phases files-big for Mia. The upload of two files of 10 MiB can take "
        + "some minutes. Then wait one hour for Microsoft Search."
    ),
    "sharepoint-team-files": (
        "Run seed.py apply --phases team-files for Mia, after the team exists and its SharePoint "
        + "site is ready. Then run record_all.sh discover again."
    ),
}
PROBES: Mapping[str, tuple[int, str, int]] = {
    "sharepoint-seed-files": (1, f"{SEED_FOLDER}:/children", 4),
    "sharepoint-tree": (1, f"{SEED_FOLDER}/seed-v1 Contracts:/children", 3),
    "sharepoint-big-files": (1, f"{SEED_FOLDER}:/children", 12),
    "sharepoint-team-files": (1, "/me/joinedTeams#seed", 1),
}
