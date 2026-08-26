# The Terraform half of the tool registry; its Python half is `tools/__init__.py`, `shared/seam.py`
# and `server/manifest.py`. `tests/test_terraform_surface.py` fails the moment the two disagree.
#
# Written out, not generated: a generator would copy a misspelled permission into this file and
# every gate would stay green.
locals {
  # SAME ORDER as `_TOOL_MODULES`, and a list rather than a map: a `for` over a map iterates in
  # lexical key order, which would derive a permission order the pod never computes.
  tool_registry = [
    { name = "get_me", permissions = ["User.Read"] },
    { name = "list_chats", permissions = ["Chat.Read"] },
    { name = "list_teams", permissions = ["Team.ReadBasic.All"] },
    { name = "list_channels", permissions = ["Channel.ReadBasic.All"] },
    { name = "browse_channel", permissions = ["ChannelMessage.Read.All"] },
    { name = "search_messages", permissions = ["Chat.Read", "ChannelMessage.Read.All"] },
    { name = "read_message", permissions = ["Chat.Read", "ChannelMessage.Read.All"] },
    { name = "list_meeting_transcripts", permissions = ["OnlineMeetings.Read", "OnlineMeetingTranscript.Read.All"] },
    { name = "read_transcript", permissions = ["OnlineMeetingTranscript.Read.All"] },
    { name = "list_meeting_recordings", permissions = ["OnlineMeetings.Read", "OnlineMeetingRecording.Read.All", "User.Read"] },
  ]

  tool_names = [for tool in local.tool_registry : tool.name]

  # `ALWAYS_ON`. Joins every selection, which is why no preset below names it.
  always_on = "get_me"

  # `PRESETS`, verbatim. `teams` is derived from the registry here and in the pod alike.
  presets = {
    teams             = local.tool_names
    teams-chat        = ["list_chats"]
    teams-messages    = ["list_chats", "search_messages", "read_message"]
    teams-channels    = ["list_teams", "list_channels", "browse_channel"]
    teams-transcripts = ["list_chats", "list_meeting_transcripts", "read_transcript"]
    teams-recordings  = ["list_chats", "list_meeting_recordings"]
    teams-meetings    = ["list_chats", "list_meeting_transcripts", "read_transcript", "list_meeting_recordings"]
  }

  # `shared/seam.py:REQUESTABLE_PERMISSIONS` — the closed set this connector may ever ask for.
  requestable_permissions = [
    "User.Read",
    "Chat.Read",
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "ChannelMessage.Read.All",
    "OnlineMeetings.Read",
    "OnlineMeetingTranscript.Read.All",
    "OnlineMeetingRecording.Read.All",
  ]

  # `server/manifest.py:NEEDS_ADMIN_CONSENT`. Not derivable: needing consent is Microsoft's rule
  # about the permission, and no tool file knows it. The `false` entries are required, not padding —
  # a precondition in main.tf asserts a verdict for every requestable permission.
  needs_admin_consent = {
    "User.Read"                        = false
    "Chat.Read"                        = false
    "Team.ReadBasic.All"               = false
    "Channel.ReadBasic.All"            = false
    "ChannelMessage.Read.All"          = true
    "OnlineMeetings.Read"              = false
    "OnlineMeetingTranscript.Read.All" = true
    "OnlineMeetingRecording.Read.All"  = true
  }

  # `shared/seam.py:graph_scope`. The authorize request's spelling of a permission, as opposed to
  # Entra's.
  graph_scope_prefix = "https://graph.microsoft.com/"

  # `auth.py:_REQUIRED_SCOPES`. Hard-coded in the application, so deliberately not a variable here: a
  # knob would let a caller register a scope name that fails FastMCP's own check with nothing here wrong.
  api_scope_name = "access_as_user"

  # `auth.py:build_auth` — FastMCP AzureProvider's own default callback path, and therefore not a
  # caller's choice.
  callback_path = "/auth/callback"
}
