import html
import re
from collections.abc import Callable, Mapping

from tests.e2e.recording.families import Scrubber

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
        "teams_read_transcript",
    }
)
READ_POSTS: Mapping[str, tuple[str, ...]] = {
    "teams_search_messages": ("POST /v1.0/search/query",),
}
_POSTS = "/v1.0/teams/*/channels/*/messages"
_REPLIES = f"{_POSTS}/*/replies"
_CHAT_MESSAGE = "/v1.0/chats/*/messages/*"
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
        f"POST {_CHAT_MESSAGE}/setReaction",
        f"POST {_CHAT_MESSAGE}/unsetReaction",
    ),
    "teams_delete_message": (
        f"POST {_POSTS}/*/softDelete",
        f"POST {_REPLIES}/*/softDelete",
        "POST /v1.0/me/chats/*/messages/*/softDelete",
    ),
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
INVITERS = frozenset({"teams_create_meeting", "teams_update_meeting"})
ADDRESSES: Mapping[str, frozenset[str]] = {"SEED_GUEST_UPN": INVITERS}
PREFIXES = ("/v1.0/teams/", "/v1.0/chats/")
THREAD_ID = (
    re.compile(r"[\w\-=.]+@thread\.(?:v2|tacv2|skype)"),
    re.compile(r"[\w\-=.]+@(?:[a-z]{2,4}\.){2,3}spaces"),
)
SCHEMA: Mapping[str, str] = {
    **dict.fromkeys(
        ("tenantId", "userId", "chatId", "teamId", "channelId", "replyToId", "etag", "threadId")
        + ("replyChatMessageId", "calendarEventId", "externalId", "teamsAppId")
        + ("meetingId", "callId", "contentCorrelationId"),
        "id",
    ),
    **dict.fromkeys(("topic", "mentionText"), "text"),
    **dict.fromkeys(
        ("lastUpdatedDateTime", "lastEditedDateTime", "deletedDateTime", "creationDateTime")
        + ("endDateTime", "visibleHistoryStartDateTime", "lastMessageReadDateTime")
        + ("meetingStartDateTime", "meetingEndDateTime", "joinDateTime", "leaveDateTime"),
        "date",
    ),
    **dict.fromkeys(
        ("chatType", "membershipType", "messageType", "reactionType", "locale", "role")
        + ("roles", "userIdentityType", "scope"),
        "enum",
    ),
    **dict.fromkeys(
        ("isArchived", "isHidden", "isDeleted", "isDialInBypassEnabled", "messageId")
        + ("totalParticipantCount", "totalAttendanceInSeconds", "durationInSeconds"),
        "number",
    ),
    **dict.fromkeys(
        ("joinWebUrl", "contentUrl", "thumbnailUrl", "transcriptContentUrl", "recordingContentUrl"),
        "url",
    ),
    "upn": "address",
    **dict.fromkeys(
        ("members", "onlineMeetingInfo", "organizer", "viewpoint", "lastMessagePreview")
        + ("eventDetail", "application", "device", "attachments", "mentions", "mentioned")
        + ("reactions", "channelIdentity", "participants", "attendees", "identity")
        + ("chatInfo", "lobbyBypassSettings", "replies", "meetingOrganizer")
        + ("attendanceRecords", "attendanceIntervals"),
        "object",
    ),
}
_MEETING = (
    "Run record_all.sh meeting all. Mia, Anna and Tom join the meeting. As Mia, start the "
    + "recording and the transcription. Each person reads aloud the lines of that person in "
    + "the transcript of scripts/dogfood/seed/corpus/teams.yaml. Then all three stop and leave."
)
_SEED_ORDER = (
    "Run run_all.sh apply with --phases teams,teams-posts,teams-chats for the indexes 1, 2 and 3, "
    + "in this order. Then wait one hour for the search index."
)
NEEDS: Mapping[str, str] = {
    "teams-team": (
        'Sign in to Teams as Mia. Create a team named "seed-v1 team". Add Anna and Tom as the '
        + "only other members."
    ),
    "teams-seed-team": (
        f"{_SEED_ORDER} Mia creates the team, its channels and its posts. The login of Mia must "
        + "have consented to Team.Create and Channel.Create. Then run record_all.sh discover again."
    ),
    "teams-seed-chats": f"{_SEED_ORDER} Then run record_all.sh discover again.",
    "teams-private-channel": (
        "This tenant refuses to create a private channel. An administrator switches on "
        + '"Create private channels" in the Teams admin centre, under Teams policies. Then run '
        + "run_all.sh apply --phases teams,teams-posts,teams-chats for the index 1, with "
        + "SEED_TEAMS_PRIVATE=1. Then run record_all.sh discover again."
    ),
    "teams-chat": (
        "Sign in to Teams as Mia. Start a group chat with Anna and Tom. Send one message in the "
        + "chat."
    ),
    "teams-meeting": _MEETING,
    "teams-meeting-attendance": _MEETING,
}
_SEED_CHAT = "/me/chats?$filter=topic eq 'seed-v1 case-teams-unread chat'"
PROBES: Mapping[str, tuple[int, str, int]] = {
    "teams-team": (1, "/me/joinedTeams", 1),
    "teams-seed-team": (1, "/me/joinedTeams#seed", 1),
    "teams-seed-chats": (1, _SEED_CHAT, 1),
    "teams-private-channel": (1, "/teams/{private-channel}/channels", 1),
    "teams-chat": (1, "/me/chats", 1),
    "teams-meeting-attendance": (1, "/me/onlineMeetings/{meeting}/attendanceReports", 1),
    "teams-meeting": (1, "/me/onlineMeetings/{meeting}/transcripts", 1),
}
_STAMP = r"-?(?:\d+:)?\d{1,2}:\d{1,2}[.,]\d{1,3}"
_TIMING = re.compile(rf"{_STAMP} --> {_STAMP}")
_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+([^>]*)>(.*?)(?:</v>)?$")
_MARKUP = re.compile(r"<[^>]*>")


def _spoken(text: Callable[[str], str], line: str) -> str:
    voice = _VOICE.match(line.strip())
    speaker = html.unescape(voice[1]).strip() if voice else ""
    said = voice[2] if voice else line
    words = " ".join(html.unescape(_MARKUP.sub("", said)).replace("\xa0", " ").split())
    kept = html.escape(text(words), quote=False) if words else ""
    return f"<v {html.escape(text(speaker), quote=False)}>{kept}</v>" if speaker and kept else kept


def _cue(text: Callable[[str], str], number: int, lines: list[str]) -> str | None:
    for at, line in enumerate(lines):
        if timing := _TIMING.match(line):
            said = [one for one in (_spoken(text, rest) for rest in lines[at + 1 :]) if one]
            return "\n".join([f"cue-{number}", timing[0], *said]) if said else None
    return None


def vtt(text: Callable[[str], str], raw: str) -> str:
    cues: list[str] = []
    for block in re.split(r"\n\s*\n", raw.removeprefix("\ufeff").replace("\r\n", "\n")):
        if (cue := _cue(text, len(cues) + 1, block.split("\n"))) is not None:
            cues.append(cue)
    return "\n\n".join(["WEBVTT", *cues]) + "\n"


BODIES: Mapping[str, Scrubber] = {"text/vtt": vtt}
