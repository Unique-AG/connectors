_GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"

REQUESTABLE_PERMISSIONS: frozenset[str] = frozenset(
    {
        "User.Read",
        "Chat.Read",
        "Team.ReadBasic.All",
        "Channel.ReadBasic.All",
        "ChannelMessage.Read.All",
        "ChatMessage.Send",
        "ChannelMessage.Send",
        "OnlineMeetings.Read",
        "OnlineMeetingTranscript.Read.All",
        "CallTranscripts.Read.All",
        "OnlineMeetingRecording.Read.All",
        "ChannelMessage.ReadWrite",
        "Chat.ReadWrite",
        "Chat.Create",
        "ChatMember.ReadWrite",
        "OnlineMeetings.ReadWrite",
        "OnlineMeetingArtifact.Read.All",
        "Mail.Read",
        "Mail.Read.Shared",
        "People.Read",
        "MailboxSettings.Read",
        "Mail.ReadWrite",
        "Mail.ReadWrite.Shared",
        "Mail.Send",
        "Mail.Send.Shared",
        "Mail.ReadBasic",
        "MailboxSettings.ReadWrite",
        "Calendars.Read",
        "Calendars.Read.Shared",
        "Calendars.ReadBasic",
        "Calendars.ReadWrite",
        "Calendars.ReadWrite.Shared",
        "Files.Read.All",
        "Files.ReadWrite.All",
        "Sites.Read.All",
        "Sites.ReadWrite.All",
        "Notes.Read",
        "Notes.Read.All",
        "Notes.Create",
        "Notes.ReadWrite",
        "Place.Read.All",
        "Group.Read.All",
        "Contacts.Read",
        "Contacts.ReadWrite",
    }
)


def graph_scope(permission: str) -> str:
    return f"{_GRAPH_SCOPE_PREFIX}{permission}"


def named_permissions(permissions: tuple[str, ...]) -> str:
    if len(permissions) == 1:
        return permissions[0]
    return " and ".join((", ".join(permissions[:-1]), permissions[-1]))
