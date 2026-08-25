# The one file in this module that says something the application also says.
#
# It is a second, hand-written statement of `_TOOL_MODULES` and `PRESETS` in
# `src/office_365_mcp/tools/__init__.py`, of `REQUESTABLE_PERMISSIONS` in
# `src/office_365_mcp/shared/seam.py`, and of `NEEDS_ADMIN_CONSENT` in
# `src/office_365_mcp/server/manifest.py`. `tests/test_terraform_surface.py` fails the moment the
# two disagree.
#
# Written out rather than generated, for the reason `tests/test_tool_selection.py` gives above
# `PRESET_COST`: a derivation agrees with any mistake in what it derives from. A generator would
# copy a misspelled `Chat.Raed` into this file and every gate would stay green. Hand-written, this
# is a second witness — and the pytest that compares them is what turns two copies into a check.
#
# TRAP: nothing in this file may reference a `var.*`. That is exactly what makes it legal for a
# `variable ... validation` block to read these locals. A validation that names a local which
# transitively depends on the variable being validated is a hard
# `Cycle: local.selected (expand), var.tools_enabled (validation)`. The var-dependent half of the
# composition lives in selection.tf, and nothing there may ever be named from a validation.
locals {
  # SAME ORDER as `_TOOL_MODULES`, and a LIST rather than a map on purpose: a `for` expression over
  # a map iterates in lexical key order, which would derive a different permission order than the
  # pod's `dict.fromkeys` and make the `tool_surface` output stop matching the service's own
  # GET /manifest — the one artifact an operator diffs it against.
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
    # `User.Read` last, for the organiser-only check. It dedupes back to position 0 in the resolved
    # list, which is the first-occurrence rule working rather than a mis-ordered row.
    { name = "list_meeting_recordings", permissions = ["OnlineMeetings.Read", "OnlineMeetingRecording.Read.All", "User.Read"] },
  ]

  tool_names = [for tool in local.tool_registry : tool.name]

  # `ALWAYS_ON`. Joins every selection, so no deployment asks for less than `User.Read` — the
  # least-privileged delegated permission Microsoft publishes, needing no administrator — and none
  # asks for zero permissions. It is the one deliberate exception to "the selection is exactly these
  # tools", and the reason no preset below names `get_me`.
  always_on = "get_me"

  # `PRESETS`, verbatim. `teams` is derived from the registry in both places, so a tool landing in
  # the registry widens it here and in the pod at once — which is precisely why `deployment_env`
  # publishes TOOLS_ENABLED and never TOOLS_PRESET (see outputs.tf).
  #
  # TRAP: permissions do not encode reachability. `teams-messages` without `search_messages` asks
  # for the identical three permissions and exposes a `read_message` nothing in it can address. Do
  # not "simplify" a preset by dropping a tool whose permissions another tool already covers.
  presets = {
    teams             = local.tool_names
    teams-chat        = ["list_chats"]
    teams-messages    = ["list_chats", "search_messages", "read_message"]
    teams-channels    = ["list_teams", "list_channels", "browse_channel"]
    teams-transcripts = ["list_chats", "list_meeting_transcripts", "read_transcript"]
    teams-recordings  = ["list_chats", "list_meeting_recordings"]
    teams-meetings    = ["list_chats", "list_meeting_transcripts", "read_transcript", "list_meeting_recordings"]
  }

  # `shared/seam.py:REQUESTABLE_PERMISSIONS` — the closed set this connector may ever ask for,
  # enforced as a plan-time precondition in main.tf.
  #
  # It earns its keep against exactly one mistake: a misspelling in `tool_registry` above.
  # `Chat.Raed` satisfies every other check in this module, and without this ceiling it is only ever
  # compared with itself — the index `oauth2_permission_scope_ids["Chat.Raed"]` reads a resource
  # attribute, so it is unknown at plan and the failure lands at APPLY, possibly after the
  # application object already exists.
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

  # `server/manifest.py:NEEDS_ADMIN_CONSENT`. Not derived and not derivable: needing consent is
  # Microsoft's rule about the permission, and no tool file knows it.
  #
  # The `false` entries are what make the table checkable — a precondition in main.tf asserts it
  # answers for every requestable permission, so a permission added without a verdict fails the plan
  # instead of being reported as "no administrator needed". That is the same assertion
  # `_needs_admin_consent` makes in the server, for the same reason: telling an operator no
  # administrator is needed when one is means every sign-in fails at "Need admin approval".
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
  # Entra's — the two differ by this prefix and nothing else.
  graph_scope_prefix = "https://graph.microsoft.com/"

  # `auth.py:_REQUIRED_SCOPES`. Hard-coded in the application, so it is not a variable here: a knob
  # would let a caller register a scope name that makes every request fail FastMCP's own scope check
  # with nothing in this module wrong. Entra omits OIDC scopes from the `scp` claim, so a custom
  # scope is the only gate on the session token there is.
  api_scope_name = "access_as_user"

  # `auth.py:build_auth` — FastMCP AzureProvider's own default callback path, and therefore not a
  # caller's choice. Registering anything else applies cleanly and then fails every sign-in.
  callback_path = "/auth/callback"
}
