import re
from collections.abc import Mapping

READ_TOOLS = frozenset(
    {
        "teams_list_my_teams",
        "teams_list_channels",
        "teams_get_channel_files_folder",
        "teams_browse_channel",
        "teams_list_chats",
        "teams_list_chat_members",
        "teams_list_chat_messages",
        "teams_read_message",
        "teams_search_messages",
        "teams_list_meeting_recordings",
        "teams_list_meeting_transcripts",
    }
)
READ_POSTS: Mapping[str, tuple[str, ...]] = {
    "teams_search_messages": ("POST /v1.0/search/query",),
}
_POSTS = "/v1.0/teams/*/channels/*/messages"
_REPLIES = f"{_POSTS}/*/replies"
_MEETINGS = "/v1.0/me/onlineMeetings"
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "teams_list_message_replies": (),
    "teams_read_meeting": (),
    "teams_send_channel_message": (f"POST {_POSTS}", f"POST {_REPLIES}"),
    "teams_send_channel_message_with_files": (f"POST {_POSTS}", f"POST {_REPLIES}"),
    "teams_edit_message": (f"PATCH {_POSTS}/*", f"PATCH {_REPLIES}/*"),
    "teams_react_to_message": (
        f"POST {_POSTS}/*/setReaction",
        f"POST {_POSTS}/*/unsetReaction",
        f"POST {_REPLIES}/*/setReaction",
        f"POST {_REPLIES}/*/unsetReaction",
    ),
    "teams_delete_message": (f"POST {_POSTS}/*/softDelete", f"POST {_REPLIES}/*/softDelete"),
    "teams_create_meeting": (f"POST {_MEETINGS}/createOrGet",),
    "teams_update_meeting": (f"PATCH {_MEETINGS}/*",),
    "teams_delete_meeting": (f"DELETE {_MEETINGS}/*",),
    "teams_create_chat": ("POST /v1.0/chats",),
    "teams_rename_chat": ("PATCH /v1.0/chats/*",),
    "teams_add_chat_member": ("POST /v1.0/chats/*/members",),
    "teams_remove_chat_member": ("DELETE /v1.0/chats/*/members/*",),
    "teams_send_chat_message": ("POST /v1.0/chats/*/messages",),
    "teams_send_chat_message_with_files": ("POST /v1.0/chats/*/messages",),
}
CREATED_ONLY: Mapping[str, int] = dict.fromkeys(
    ("teams_rename_chat", "teams_add_chat_member", "teams_remove_chat_member")
    + ("teams_send_chat_message", "teams_send_chat_message_with_files"),
    0,
)
EXTERNAL = frozenset(
    {"teams_send_channel_message", "teams_send_channel_message_with_files"}
    | {
        "teams_create_chat",
        "teams_rename_chat",
        "teams_add_chat_member",
        "teams_remove_chat_member",
    }
    | {"teams_send_chat_message", "teams_send_chat_message_with_files"}
)
PREFIXES = ("/v1.0/teams/", "/v1.0/chats/")
THREAD_ID = (
    re.compile(r"[\w\-=.]+@thread\.(?:v2|tacv2|skype)"),
    re.compile(r"[\w\-=.]+@(?:[a-z]{2,4}\.){2,3}spaces"),
)
SCHEMA: Mapping[str, str] = {
    **dict.fromkeys(
        ("tenantId", "userId", "chatId", "teamId", "channelId", "replyToId", "etag", "threadId")
        + ("replyChatMessageId", "calendarEventId", "externalId", "teamsAppId"),
        "id",
    ),
    **dict.fromkeys(("topic", "mentionText"), "text"),
    **dict.fromkeys(
        ("lastUpdatedDateTime", "lastEditedDateTime", "deletedDateTime", "creationDateTime")
        + ("endDateTime", "visibleHistoryStartDateTime", "lastMessageReadDateTime"),
        "date",
    ),
    **dict.fromkeys(
        ("chatType", "membershipType", "messageType", "reactionType", "locale", "role")
        + ("roles", "userIdentityType", "scope"),
        "enum",
    ),
    **dict.fromkeys(
        ("isArchived", "isHidden", "isDeleted", "isDialInBypassEnabled", "messageId"), "number"
    ),
    **dict.fromkeys(("joinWebUrl", "contentUrl", "thumbnailUrl"), "url"),
    "upn": "address",
    **dict.fromkeys(
        ("members", "onlineMeetingInfo", "organizer", "viewpoint", "lastMessagePreview")
        + ("eventDetail", "application", "device", "attachments", "mentions", "mentioned")
        + ("reactions", "channelIdentity", "participants", "attendees", "identity")
        + ("chatInfo", "lobbyBypassSettings"),
        "object",
    ),
}
_MEETING = (
    "Sign in to Teams as Mia. Start a meeting with Anna. Turn on recording and transcription. "
    + "Join as Mia and as Anna. Talk for one minute. End the meeting. Wait one hour."
)
UNRECORDED: Mapping[str, str] = {
    "teams_read_transcript": (
        f"{_MEETING} Then add a case that reads the first transcript, and a scrub policy for the "
        + "VTT file: it holds spoken words, so the scrub refuses it today."
    ),
}
NEEDS: Mapping[str, str] = {
    "teams-team": (
        'Sign in to Teams as Mia. Create a team named "seed-v1 team". Add Anna and Tom as the '
        + "only other members."
    ),
    "teams-seed-team": (
        'Run record_all.sh seed. Mia creates the team "seed-v1 team" with a General channel, and '
        + "Anna and Tom are its only other members. The login of Mia must have consented to "
        + "Team.Create. Then run record_all.sh discover again."
    ),
    "teams-chat": (
        "Sign in to Teams as Mia. Start a group chat with Anna and Tom. Send one message in the "
        + "chat."
    ),
    "teams-meeting": _MEETING,
}
_CALENDAR = (
    "/me/calendarView?startDateTime=2026-01-01T00:00:00Z&endDateTime=2032-01-01T00:00:00Z"
    + "&$filter=isOnlineMeeting eq true&$top=1"
)
PROBES: Mapping[str, tuple[int, str, int]] = {
    "teams-team": (1, "/me/joinedTeams", 1),
    "teams-seed-team": (1, "/me/joinedTeams#seed", 1),
    "teams-chat": (1, "/me/chats", 1),
    "teams-meeting": (1, _CALENDAR, 1),
}
