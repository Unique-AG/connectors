# office-365-mcp

## Overview

office-365-mcp is a Python MCP server, built on FastMCP, that connects Microsoft 365 to MCP
clients through the Microsoft Graph API. It reaches Outlook mail and calendar, Microsoft Teams,
SharePoint and OneDrive, OneNote, and user identity. The server has 52 tools in total. A
deployment turns on a fixed subset of these 52 tools (never all of them, unless a preset or a
list names every one). This document explains what each tool does, how a deployment picks its
tools, and how sign-in and consent work.

## Tools

office-365-mcp has 52 tools, across six areas: identity, Microsoft Teams, Outlook mail, Outlook
calendar, SharePoint and OneDrive, and OneNote. One tool, get_me, is always on, in every
configuration. The Kind column is a hint to the calling client about the kind of change a tool
makes. It does not control access to the tool.

### Identity

| Tool | Kind | Permission | Admin consent | What it does |
| --- | --- | --- | --- | --- |
| get_me | Read | User.Read | No | The answer is the signed-in user's own Microsoft 365 profile: id, display name, email address, sign-in name, and job title. |

### Microsoft Teams

| Tool | Kind | Permission | Admin consent | What it does |
| --- | --- | --- | --- | --- |
| teams_list_chats | Read | Chat.Read | No | The signed-in user's Teams chats (1:1, group, meeting), newest last message first. |
| teams_list_my_teams | Read | Team.ReadBasic.All | No | The teams that the signed-in user is a member of. |
| teams_list_channels | Read | Channel.ReadBasic.All | No | The channels of one team that the signed-in user can access. |
| teams_browse_channel | Read | ChannelMessage.Read.All | Yes | One Teams channel's posts, with their newest replies. |
| teams_search_messages | Read | Chat.Read, ChannelMessage.Read.All | Yes | A full-text search across every Teams message, in chats and channels, that the signed-in user can see. |
| teams_read_message | Read | Chat.Read, ChannelMessage.Read.All | Yes | One Microsoft Teams message in full, from a handle that another tool minted. |
| teams_list_meeting_transcripts | Read | OnlineMeetings.Read, OnlineMeetingTranscript.Read.All | Yes | Whether a Teams meeting has a transcript, and a handle for each one. |
| teams_read_transcript | Read | OnlineMeetingTranscript.Read.All | Yes | One page of a Teams meeting transcript, as timestamped turns with the speaker named, not the whole file at once. |
| teams_list_meeting_recordings | Read | User.Read, OnlineMeetings.Read, OnlineMeetingRecording.Read.All | Yes | Whether a meeting recording exists, how long it runs, and who can download it. The answer is metadata only, never the video itself. |

### Outlook mail

| Tool | Kind | Permission | Admin consent | What it does |
| --- | --- | --- | --- | --- |
| outlook_search_mail | Read | Mail.Read, User.Read | No | Finds a message anywhere in the signed-in user's mailbox. |
| outlook_read_mail | Read | Mail.Read | No | One message's full text, from a handle that another tool minted. |
| outlook_browse_folders | Read | Mail.Read | No | One level of the mail folder tree, and a handle for each folder. |
| outlook_find_recipient | Read | Mail.Read, People.Read, User.Read | No | The email address behind a display name. A draft therefore goes to the real address, not a guess. |
| outlook_read_thread | Read | Mail.Read | No | Every message of one conversation that is in this mailbox. |
| outlook_list_mail | Read | Mail.Read | No | The newest messages of one folder, in receipt order. |
| outlook_get_mailbox_settings | Read | MailboxSettings.Read | No | What acts quietly on this mailbox — the rules, the automatic reply, and the categories — and what this tool cannot show. |
| outlook_mark_mail | Write, changes or removes | Mail.ReadWrite | No | The read status, the follow-up flag, and the importance, on up to twenty messages. |
| outlook_move_mail | Write, changes or removes | Mail.ReadWrite | No | Moves messages into another folder. This connector erases mail only by moving it to Deleted Items. |
| outlook_draft_mail | Write, adds | Mail.ReadWrite | No | A new message, composed into Drafts. The tool cannot send it. |
| outlook_draft_reply | Write, adds | Mail.ReadWrite | No | A reply or a forward, composed into Drafts and left there. |
| outlook_send_draft | Write, changes or removes | Mail.Send, Mail.ReadBasic | No | The only tool in this connector that puts mail on the wire. It sends a draft that this connector composed. |
| outlook_set_automatic_reply | Write, safe to repeat | MailboxSettings.ReadWrite | No | Turns the out-of-office reply on for a fixed period, or off. The reply never runs with no end date. |
| outlook_disable_mail_rule | Write, safe to repeat | MailboxSettings.ReadWrite | No | Turns one existing inbox rule off, and nothing else. |

### Outlook calendar

| Tool | Kind | Permission | Admin consent | What it does |
| --- | --- | --- | --- | --- |
| outlook_list_calendars | Read | Calendars.Read, Calendars.Read.Shared, User.Read | No | Every calendar that this mailbox reaches — the user's own and each one delegated — and a handle for each one. |
| outlook_list_events | Read | Calendars.Read, Calendars.Read.Shared | No | One calendar's occurrences over a window, never a recurrence rule. |
| outlook_read_event | Read | Calendars.Read, Calendars.Read.Shared | No | One event in full, from a handle that another tool minted, with every attendee and each one's reply. |
| outlook_create_event | Write, adds | Calendars.ReadWrite | No | One new event on the user's own calendar. The tool creates it and sends invitations in one call. |
| outlook_create_event_on_behalf | Write, adds | Calendars.ReadWrite.Shared, Calendars.Read, Calendars.Read.Shared | No | One event on a calendar delegated by another person, sent under that person's own name. |

### SharePoint and OneDrive

| Tool | Kind | Permission | Admin consent | What it does |
| --- | --- | --- | --- | --- |
| sharepoint_search_files | Read | Files.Read.All | Yes | Searches the files and folders that the signed-in user can see, across OneDrive and SharePoint. |
| sharepoint_browse_folder | Read | Files.Read.All | Yes | Lists every item directly inside one folder, in OneDrive or SharePoint, one level only. |
| sharepoint_read_file | Read | Files.Read.All | Yes | The answer is the content of one file, in its original format, or converted to PDF. |

### OneNote

| Tool | Kind | Permission | Admin consent | What it does |
| --- | --- | --- | --- | --- |
| onenote_list_notebooks | Read | Notes.Read | No | Every notebook that the user owns, or that is shared with the user, with each notebook's sections. |
| onenote_list_pages | Read | Notes.Read | No | Finds pages by title, across notebooks or in one section. Microsoft Graph has no full-text search for OneNote. |
| onenote_read_page | Read | Notes.Read | No | Reads the HTML of one page, exactly as Microsoft stores it. |
| onenote_create_page | Write, adds | Notes.Create | No | Writes a new page into the signed-in user's OneNote. No attachments or images. |
| onenote_append_to_page | Write, adds | Notes.ReadWrite | No | Adds HTML to the end of one page. It cannot insert, edit, or erase existing content. |
| onenote_preview_page | Read | Notes.Read | No | A short snippet, up to 300 characters, of one page, plus a preview image address. |
| onenote_read_resource | Read | Notes.Read | No | Fetches the bytes of one image or file that is embedded in a page, with its real media type. |
| onenote_find_notebook_from_url | Read | Notes.Read | No | Resolves a OneNote web address into a notebook handle. |
| onenote_list_recent_notebooks | Read | Notes.Read | No | Notebooks that the signed-in user opened recently, per Microsoft's own record. |
| onenote_list_sections | Read | Notes.Read | No | Sections and section groups directly under one notebook or section group, one level at a time. |
| onenote_create_notebook | Write, adds | Notes.Create | No | Creates a new, empty notebook for the signed-in user. |
| onenote_create_section | Write, adds | Notes.Create | No | Creates a new, empty section directly under a notebook or section group. |
| onenote_create_section_group | Write, adds | Notes.Create | No | Creates a new, empty section group directly under a notebook or another section group. |
| onenote_edit_page | Write, changes or removes | Notes.ReadWrite | No | Adds content next to an element on one page, or replaces one, through 1 to 20 batched commands. |
| onenote_rename_page | Write, changes or removes, safe to repeat | Notes.ReadWrite | No | Changes the title of one page, and nothing else. |
| onenote_copy_page | Write, adds | Notes.Read, Notes.Create | No | Starts a copy of one page into another section, on Microsoft's own systems. The answer is a handle for the operation. |
| onenote_copy_section | Write, adds | Notes.Create | No | Starts a copy of one section into another notebook or section group. The answer is a handle for the operation. |
| onenote_copy_notebook | Write, adds | Notes.Create | No | Starts a copy of a whole notebook into the user's own OneDrive, on Microsoft's own systems. The answer is a handle for the operation. |
| onenote_get_operation | Read | Notes.Read | No | Polls a copy operation, started by onenote_copy_page, onenote_copy_section, or onenote_copy_notebook, for its result. |
| onenote_delete_page | Write, changes or removes, safe to repeat | Notes.ReadWrite | No | Erases one page outright. The tool always asks the user to approve this first, because Microsoft Graph keeps no recycle bin for OneNote. |

## Presets

A deployment turns tools on in exactly one of two ways. The first way is a named preset. The
second way is an exact list of tool names, set as the TOOLS_ENABLED configuration. A deployment
must pick exactly one way. It must not set both, and it must not leave both unset. Three places
enforce this rule: the Helm chart schema, the Terraform module, and the server's own startup
check. This is not a preset plus an add-on. It is two ways to name one choice. The tool get_me is
always on, in every configuration, so no preset or list needs to name it. A deployment cannot
start from a preset and then add or remove one tool. For a mix of tools that no preset covers,
name every wanted tool in the exact list instead. There are 20 presets. This table names what
each preset turns on, besides get_me.

| Preset | What it turns on |
| --- | --- |
| teams | Every Teams tool this server has: chats, teams, channels, channel posts, message search, one message in full, transcripts, and recordings. |
| teams-chat | The list of the signed-in user's Teams chats, and nothing else. It cannot read a chat message. |
| teams-messages | Finds a message anywhere, and reads it in full (teams_list_chats, teams_search_messages, teams_read_message). |
| teams-channels | Walks a team's channels, and reads the posts in one channel (teams_list_my_teams, teams_list_channels, teams_browse_channel). |
| teams-transcripts | Finds a meeting, and reads the transcript of it (teams_list_chats, teams_list_meeting_transcripts, teams_read_transcript). |
| teams-recordings | Says whether a meeting was recorded, and who can get the recording (teams_list_chats, teams_list_meeting_recordings). |
| teams-meetings | Both transcripts and recordings, for one meeting (teams_list_chats, teams_list_meeting_transcripts, teams_read_transcript, teams_list_meeting_recordings). |
| outlook-read | Finds a message, reads it in full, walks the folder tree, reads a thread, lists a folder, and resolves a name to an address. |
| outlook-write | Everything in outlook-read, plus marking, filing, and drafting mail (outlook_mark_mail, outlook_move_mail, outlook_draft_mail, outlook_draft_reply). |
| outlook-send | Everything in outlook-write, plus sending a draft that this connector composed (outlook_send_draft). |
| outlook-mailbox | Shows what quietly acts on the mailbox: the rules, the automatic reply, and the categories (outlook_get_mailbox_settings). |
| outlook-automate | Everything in outlook-mailbox, plus setting the automatic reply and turning an inbox rule off (outlook_set_automatic_reply, outlook_disable_mail_rule). |
| outlook-calendar | Names every calendar that the mailbox reaches, and reads what sits on one (outlook_list_calendars, outlook_list_events, outlook_read_event). |
| outlook-calendar-write | Everything in outlook-calendar, plus creating one event on the user's own calendar (outlook_create_event). |
| outlook-calendar-delegate | Everything in outlook-calendar-write, plus creating an event on a calendar delegated by another person (outlook_create_event_on_behalf). |
| sharepoint-search | Finds a file in OneDrive or on a SharePoint site, and lists one level of a folder (sharepoint_search_files, sharepoint_browse_folder). |
| sharepoint-read | Everything in sharepoint-search, plus reading one file itself, or its PDF form (sharepoint_read_file). |
| onenote-read | Lists notebooks, sections, and pages, and reads or previews a page (eight tools, from onenote_list_notebooks to onenote_list_sections). |
| onenote-write | Everything in onenote-read, plus creating, editing, and copying notebooks, sections, and pages (eleven more tools). |
| onenote-delete | Everything in onenote-write, plus erasing one page outright (onenote_delete_page). |

**Note:** Terraform (in another repository) writes the Entra application registration, and Argo
(in another repository) writes the pod's active tool selection. Nothing compares the two on its
own.

## Permissions and consent

Each tool needs one or more Microsoft Graph permissions, and the Tools section names each one. A
deployment asks for the union of every active tool's permissions, one time, at sign-in. It never
asks again per call, and it never asks later for a permission that no tool requested at sign-in.
Before any user can sign in, some permissions need a tenant administrator to grant them, and the
Tools section marks these. After sign-in, each call draws the one permission it needs from this
already-granted set, for the signed-in user. It does not ask again.

## Deployment

A deployment sets its tool surface under `mcpConfig.tools`, in the Helm chart's values file. It
sets exactly one of two keys, `preset` or `enabled`. It never sets both, and it never leaves both
unset.

```yaml
mcpConfig:
  tools:
    preset: teams        # or: enabled: get_me,teams_list_chats
```

The `preset` key names one of the 20 presets in the Presets table. The `enabled` key names an
exact, comma-separated list of tool names instead. A deployment that needs a mix that no preset
covers uses `enabled`, and names every wanted tool.

Administrator consent is a separate step from setting the tool surface. It happens in Terraform.
When the caller sets its `service_principal_configuration` input, the Terraform module can grant
the needed consent itself. It does this as part of `terraform apply`, through a tenant-wide
delegated permission grant. When that input is not set, the module grants no consent on its own.
A tenant administrator must grant it instead. The administrator can use the Entra portal, or the
module's own `admin_consent_url` output. Either way, the module's own README asks the operator to
make sure that the permissions show as granted, in Entra under App registrations.

Terraform writes the Entra application registration. Argo writes the deployed pod's tool
selection, through the chart values in this section. No automatic step compares these two. A
mismatch is possible, and it produces no warning. A registration narrower than the pod fails
every sign-in at the authorize step, with nothing in the pod's own logs to explain why.

The check is manual, and it is repeatable. Run `curl $PUBLIC_BASE_URL/manifest` against the
deployed pod. It answers with the resolved tool selection and the exact permission list, in the
tool registry's order. Then run `terraform output tool_surface` in the Terraform module. It
answers with the same shape: the preset, the tools, the permissions, and which permissions need
admin consent, in the same order. Compare the two permission lists, line for line. If the pod's
list names a permission that the Terraform output does not, every sign-in fails at the authorize
step. If the Terraform output names more permissions than the pod uses, the tenant carries
standing access that no tool spends.

## Limitations

office-365-mcp is meant to replace two other services: teams-mcp and outlook-semantic-mcp. It
works differently: every tool call reaches Microsoft Graph directly, and it stores nothing
beyond an OAuth token. The tables below name what a reader gains and loses against each service.
Neither service has a formal deprecation date yet, and both remain in active development. This
section is a comparison of the current state, not a finished handover. A comment in teams-mcp's
message data states that its fields were "shaped to match the fields" office-365-mcp uses for
the same resource.

### Compared to teams-mcp

| Capability | office-365-mcp | teams-mcp |
| --- | --- | --- |
| Send or reply to a Teams message | No | Yes |
| Message reactions in a tool's answer | No | Yes |
| Full message body in one search call | No, a second call is needed | Yes |
| Capture a transcript into Unique's knowledge base | No | Yes, opt-in, needs a database |
| Read the replies inside a channel thread | Yes | No, root posts only |
| Read a transcript, or a recording's metadata, live, with no configuration | Yes | No, ingest only |
| Plain, normalized text, not raw HTML | Yes | No |

### Compared to outlook-semantic-mcp

| Capability | office-365-mcp | outlook-semantic-mcp |
| --- | --- | --- |
| Read a shared or delegated mailbox | No, own mailbox only | Yes |
| Search the words inside an attachment | No, file name only | Yes |
| Change or cancel an event, or answer an invitation | No, create only | Yes |
| Add an attachment to a draft | No | Yes |
| Send a message outright | Yes | No, draft only |
| Mark a message read or unread, set its flag or importance, or move it | Yes | No |
| Read a whole conversation across folders, in one call | Yes | No, one message at a time |
| Read and change the automatic reply, or turn off a rule | Yes | No |
