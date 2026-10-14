# office-365-mcp use cases

This page lists what people do with office-365-mcp. Each use case has a stable ID, an example
prompt, the tools it needs, and a status. The list is the input for two later tasks. UN-27226 turns
the use cases into tests. UN-27222 changes the tools, the parameters, and the docs to match.

This page records the state of testing. It is not a promise about what the server does. For the
tool reference, read `README.md`.

## How to read a use case

| Field | Meaning |
| --- | --- |
| **Prompt** | An example of what a user says to the model. A test sends this text, or a close copy. |
| **Tools** | The tools that the model calls, in the usual order. |
| **Preset** | The smallest preset that holds every tool. `exact list` means no preset holds them all. |
| **Pass if** | What a tester sees when the use case works. |
| **Status** | One of the values below. |
| **Notes** | The tool or parameter that limits the use case, and the cause of the limit. |

| Status | Meaning |
| --- | --- |
| `working` | A person ran it against a real tenant, and it did what the use case says. |
| `partly working` | A person ran it. It works with a limit that the notes name. |
| `gap` | A person ran it. It fails. |
| `expected gap` | A tool description already states a limit that blocks it. Nobody ran it yet. |
| `untested` | Nobody ran it yet. |

A `gap` or an `expected gap` has one cause, named in the notes:

- **tool**: no tool does it.
- **parameter**: a tool exists, but it lacks an argument.
- **description**: the tool can do it, but a model cannot tell.
- **preset**: every tool exists, but no preset holds them together.
- **consent**: it needs an admin consent that a deployment does not have.
- **graph**: Microsoft Graph cannot do it. UN-27222 cannot fix this.

## Test log

| Date | Build | Tenant | Tester | Use cases run |
| --- | --- | --- | --- | --- |
| | | | | |

## Outlook mail

### OL-MAIL-01 Triage the inbox

- **Prompt**: "What did I get since yesterday that is unread or flagged? Tell me what needs a reply."
- **Tools**: `outlook_list_mail`, `outlook_read_mail`, `outlook_read_thread`
- **Preset**: `outlook-read`
- **Pass if**: The rows are only unread or flagged mail from the window, and the summary names the messages that need a reply.
- **Status**: `untested`
- **Notes**: `unread_only`, `flagged`, and `received_after` on `outlook_list_mail` should cover it.

### OL-MAIL-02 Find one message

- **Prompt**: "Find the mail from the vendor about the March invoice, the one with the PDF."
- **Tools**: `outlook_search_mail`, `outlook_read_mail`
- **Preset**: `outlook-read`
- **Pass if**: The right message is in the first rows, and `outlook_read_mail` shows the attachment name.
- **Status**: `untested`
- **Notes**: Check `sender`, `subject`, `attachment_name`, `has_attachments`, and the two date arguments together. Graph `$search` never takes a date, so test a date window on its own.

### OL-MAIL-03 Organize mail in bulk

- **Prompt**: "Move all newsletters from last month into the Newsletters folder and mark them as read."
- **Tools**: `outlook_search_mail`, `outlook_browse_folders`, `outlook_move_mail`, `outlook_mark_mail`
- **Preset**: `outlook-write`
- **Pass if**: Every matching message is in the folder and has `is_read` true. No other message moved.
- **Status**: `working`
- **Notes**: Run by hand in a real mailbox. No recorded run yet. Also check a batch of more than 20 messages.

### OL-MAIL-04 Manage mail folders

- **Prompt**: "Create a folder Projects/Alpha under Inbox, and rename Old to Archive 2025."
- **Tools**: `outlook_browse_folders`, `outlook_create_folder`, `outlook_rename_folder`
- **Preset**: `outlook-write`
- **Pass if**: The folder tree shows the new folder and the new name.
- **Status**: `working`
- **Notes**: Run by hand in a real mailbox. Deleting a folder needs `outlook-delete`.

### OL-MAIL-05 Create and apply categories

- **Prompt**: "Make a red category called Follow-up Q4, then put it on every unread mail from my manager."
- **Tools**: `outlook_list_categories`, `outlook_create_category`, `outlook_search_mail`, `outlook_mark_mail`
- **Preset**: `exact list`
- **Pass if**: The category exists with the color, and every matching message carries it.
- **Status**: `working`
- **Notes**: Run by hand with an exact tool list. Cause of the extra step: **preset**. `outlook-write` has `outlook_mark_mail` but not `outlook_create_category`. `outlook-automate` has the reverse.

### OL-MAIL-06 Manage inbox rules

- **Prompt**: "Add a rule that moves mail from billing@example.com into Finance, and turn off my old Receipts rule."
- **Tools**: `outlook_get_mailbox_settings`, `outlook_browse_folders`, `outlook_create_mail_rule`, `outlook_update_mail_rule`, `outlook_disable_mail_rule`, `outlook_delete_mail_rule`
- **Preset**: `exact list`
- **Pass if**: `outlook_get_mailbox_settings` shows the new rule with its condition and action, and the old rule is off.
- **Status**: `working`
- **Notes**: Run by hand with an exact tool list. Cause of the extra step: **preset**. `outlook-rules` cannot list folders, so a model cannot find the folder for a move action. Also test a rule with an exception, and a forward rule, which asks the user.

### OL-MAIL-07 Draft, change, and send a mail

- **Prompt**: "Draft a mail to Anna asking for the contract by Friday. Show it to me, then send it."
- **Tools**: `outlook_find_recipient`, `outlook_draft_mail`, `outlook_update_draft`, `outlook_send_draft`
- **Preset**: `outlook-send`
- **Pass if**: A draft exists with the right address. The send asks the user to approve. The message is in Sent Items.
- **Status**: `untested`
- **Notes**: `outlook_send_draft` sends nothing if the draft changed after the question. Check this on purpose.

### OL-MAIL-08 Reply and forward

- **Prompt**: "Reply to the last message in this thread, and copy my assistant."
- **Tools**: `outlook_read_thread`, `outlook_draft_reply`, `outlook_draft_reply_all`, `outlook_send_draft`
- **Preset**: `outlook-send`
- **Pass if**: The draft quotes the thread, has the Cc address, and goes to the right people.
- **Status**: `untested`

### OL-MAIL-09 Send a mail with an attachment

- **Prompt**: "Mail this report to the team with the PDF attached."
- **Tools**: `outlook_draft_mail`, `outlook_send_draft`
- **Preset**: `outlook-send`
- **Pass if**: The sent message holds the file.
- **Status**: `expected gap`
- **Notes**: Cause: **tool**. The draft tools cannot add a file. A forward keeps the original attachments only.

### OL-MAIL-10 Read an attachment

- **Prompt**: "Open the attached spreadsheet and tell me the total in the last row."
- **Tools**: `outlook_list_attachments`, `outlook_read_attachment`
- **Preset**: `outlook-read`
- **Pass if**: The model gets the file with its real media type and answers from it.
- **Status**: `untested`
- **Notes**: The tool refuses a file above 10 MB. Test a docx, an xlsx, and a pdf. Graph gives no text extraction, so what the model reads depends on the client.

### OL-MAIL-11 Set the out-of-office reply

- **Prompt**: "Turn on my out-of-office from Monday to Friday with a short message."
- **Tools**: `outlook_set_automatic_reply`, `outlook_get_mailbox_settings`
- **Preset**: `outlook-automate`
- **Pass if**: The settings show the reply on, with the period and the text. A second call turns it off.
- **Status**: `untested`

### OL-MAIL-12 Tune Focused and Other

- **Prompt**: "Always put mail from the CEO in Focused."
- **Tools**: `outlook_list_focused_overrides`, `outlook_set_focused_override`
- **Preset**: `outlook-write`
- **Pass if**: The override is in the list. Later mail from that sender shows in Focused.
- **Status**: `untested`

### OL-MAIL-13 Work in a shared mailbox

- **Prompt**: "In the support@ mailbox, list the unread mail and move the spam to Junk."
- **Tools**: `outlook_list_mail`, `outlook_move_mail`
- **Preset**: `outlook-write`
- **Pass if**: Reads and moves apply to the shared mailbox. A change asks the user to approve.
- **Status**: `untested`
- **Notes**: Needs a shared mailbox that the test user can open. Uses the `mailbox` argument.

### OL-MAIL-14 Check a recipient before sending

- **Prompt**: "Is Anna out of office? Also check that her address is right."
- **Tools**: `outlook_find_recipient`, `outlook_get_mail_tips`
- **Preset**: `outlook-read`
- **Pass if**: The answer gives the address and shows an automatic reply, if one is on.
- **Status**: `untested`

## Outlook calendar

### OL-CAL-01 Read my day or week

- **Prompt**: "What is on my calendar tomorrow? Do I have a clash?"
- **Tools**: `outlook_list_events`, `outlook_read_event`
- **Preset**: `outlook-calendar`
- **Pass if**: Every event of the day is in the list, in the user's time zone, and a clash is named.
- **Status**: `untested`
- **Notes**: Check `time_zone` and an all-day event. Check a recurring series, which `outlook_list_event_instances` lists.

### OL-CAL-02 Respond to invites

- **Prompt**: "Accept all invites from my team for next week, and decline the Friday one with a note."
- **Tools**: `outlook_list_events`, `outlook_respond_to_invite`
- **Preset**: `outlook-calendar-write`
- **Pass if**: The organizer sees each answer. The decline holds the note.
- **Status**: `working`
- **Notes**: Run by hand in a real mailbox. `owner_response` on `outlook_list_events` should find open invites. Check this.

### OL-CAL-03 Schedule a meeting

- **Prompt**: "Find 30 minutes this week for me, Anna, and Tom. Book it with a Teams link."
- **Tools**: `outlook_check_availability`, `outlook_suggest_meeting_times`, `outlook_create_event`
- **Preset**: `outlook-calendar-write`
- **Pass if**: The event is on the calendar, has a Teams link, and each attendee got an invitation.
- **Status**: `untested`
- **Notes**: The tool sends invitations in the same call, so run it with test attendees.

### OL-CAL-04 Book a room

- **Prompt**: "Book a room for 8 people for the workshop."
- **Tools**: `outlook_find_rooms`, `outlook_create_event`
- **Preset**: `outlook-calendar-rooms`
- **Pass if**: The room is a resource attendee and accepts.
- **Status**: `untested`
- **Notes**: Cause if it fails: **consent**. `Place.Read.All` needs admin consent, and Microsoft lists rooms only after an administrator turns on buildings.

### OL-CAL-05 Reschedule or cancel

- **Prompt**: "Move the Thursday sync to Friday at 10:00. Cancel next week's one only."
- **Tools**: `outlook_list_events`, `outlook_update_event`, `outlook_cancel_event`
- **Preset**: `outlook-calendar-write`
- **Pass if**: The change reaches the right date. A change to one date leaves the series alone.
- **Status**: `untested`
- **Notes**: Test a series master and one occurrence, with both handles.

### OL-CAL-06 Create an event on a second calendar

- **Prompt**: "Add the offsite to my Team calendar, not my main one."
- **Tools**: `outlook_list_calendars`, `outlook_create_event`
- **Preset**: `outlook-calendar-write`
- **Pass if**: The event is on the named calendar.
- **Status**: `expected gap`
- **Notes**: Cause: **parameter**. `outlook_create_event` has no `calendar_ref`, and its description says "the user's own calendar". `outlook_list_events` has `calendar_ref`.

### OL-CAL-07 Act for another person

- **Prompt**: "Put a meeting on my manager's calendar for them."
- **Tools**: `outlook_list_calendars`, `outlook_create_event_on_behalf`
- **Preset**: `outlook-calendar-delegate`
- **Pass if**: The event is on the delegated calendar and goes out under the other person's name.
- **Status**: `untested`
- **Notes**: Needs a calendar that a test user delegates.

### OL-CAL-08 Share a calendar

- **Prompt**: "Let Anna see my calendar, then stop sharing it."
- **Tools**: `outlook_share_calendar`, `outlook_list_calendar_shares`, `outlook_unshare_calendar`
- **Preset**: `outlook-calendar-manage`
- **Pass if**: The share shows in the list, then disappears.
- **Status**: `untested`
- **Notes**: The share takes effect only after the person accepts. Check what the model says about this.

### OL-CAL-09 Forward an event

- **Prompt**: "Forward the board meeting invite to Tom."
- **Tools**: `outlook_forward_event`
- **Preset**: `outlook-calendar-manage`
- **Pass if**: Tom gets the invitation. The tool asks the user first.
- **Status**: `untested`

### OL-CAL-10 Read a team calendar

- **Prompt**: "What is on the Platform team's calendar this week?"
- **Tools**: `teams_list_my_teams`, `outlook_list_group_events`
- **Preset**: `outlook-group-calendar`
- **Pass if**: The events of the group calendar are in the list.
- **Status**: `untested`
- **Notes**: A row has no handle, so `outlook_read_event` cannot open it. Cause if a model needs more: **tool**.

## Outlook contacts

### OL-CON-01 Look up a contact

- **Prompt**: "What is Anna Meier's phone number?"
- **Tools**: `outlook_list_contacts`, `outlook_read_contact`
- **Preset**: `outlook-contacts`
- **Pass if**: The number comes from the contact.
- **Status**: `untested`
- **Notes**: The tool reads only the default Contacts folder. Check a person that is only in the company directory. `outlook_find_recipient` covers that case for an address, not for a phone number.

### OL-CON-02 Create and update a contact

- **Prompt**: "Save Tom Berger from Acme, tom@acme.example, as a contact. Add his mobile number."
- **Tools**: `outlook_create_contact`, `outlook_update_contact`
- **Preset**: `outlook-contacts-write`
- **Pass if**: One contact exists with both fields.
- **Status**: `untested`

## Microsoft Teams

### TM-01 Catch up on chats

- **Prompt**: "Which chats have messages I did not read? Summarize the last day of each."
- **Tools**: `teams_list_chats`, `teams_list_chat_messages`, `teams_read_message`
- **Preset**: `teams-messages`
- **Pass if**: The list shows only chats with unread messages, and each summary matches the messages.
- **Status**: `untested`
- **Notes**: `teams_list_chats` reports whether the user read the last message. It has no unread filter. Check this.

### TM-02 Search across Teams

- **Prompt**: "Where did we talk about the pricing change? Show me the messages."
- **Tools**: `teams_search_messages`, `teams_read_message`
- **Preset**: `teams-messages`
- **Pass if**: The hits come from both chats and channels, and each one opens.
- **Status**: `untested`
- **Notes**: Needs admin consent for `ChannelMessage.Read.All`. Cause if it fails: **consent**.

### TM-03 Read a channel

- **Prompt**: "What happened in the Releases channel this week? Include the replies."
- **Tools**: `teams_list_my_teams`, `teams_list_channels`, `teams_browse_channel`, `teams_list_message_replies`
- **Preset**: `teams-channels`
- **Pass if**: The posts and their replies are in the answer. A long thread shows `more_replies`.
- **Status**: `untested`

### TM-04 Post a message with a mention

- **Prompt**: "Tell Anna in our chat that the build is green. Mention her."
- **Tools**: `teams_list_chats`, `teams_list_chat_members`, `teams_send_chat_message`
- **Preset**: `teams-write`
- **Pass if**: The message is in the chat and the mention is a real mention. The tool asks first.
- **Status**: `untested`

### TM-05 Post to a channel or reply to a post

- **Prompt**: "Post in the Releases channel that v2 is out. Reply to the last post if one asks."
- **Tools**: `teams_list_channels`, `teams_send_channel_message`
- **Preset**: `teams-write`
- **Pass if**: The post or the reply is in the right thread.
- **Status**: `untested`

### TM-06 Send a file from SharePoint

- **Prompt**: "Send the Q3 deck from SharePoint to the Platform channel."
- **Tools**: `sharepoint_search_files`, `teams_send_channel_message_with_files`
- **Preset**: `teams-write-files`
- **Pass if**: The message has the file as an attachment.
- **Status**: `untested`
- **Notes**: The tool cannot upload a local file. A file must be in SharePoint already.

### TM-07 Change my own message

- **Prompt**: "Fix the typo in my last message. Delete the one before."
- **Tools**: `teams_list_chat_messages`, `teams_edit_message`, `teams_delete_message`
- **Preset**: `teams-edit`
- **Pass if**: The edit and the delete reach only the user's own messages. The tool refuses another person's message.
- **Status**: `untested`
- **Notes**: Needs admin consent for `ChannelMessage.ReadWrite`.

### TM-08 React to a message

- **Prompt**: "Give a thumbs up to Tom's last message."
- **Tools**: `teams_list_chat_messages`, `teams_react_to_message`
- **Preset**: `teams-write`
- **Pass if**: The reaction shows on the message.
- **Status**: `untested`

### TM-09 Run a group chat

- **Prompt**: "Start a group chat with Anna and Tom called Launch. Add Mia later."
- **Tools**: `teams_create_chat`, `teams_add_chat_member`, `teams_rename_chat`, `teams_remove_chat_member`
- **Preset**: `teams-chat-admin`
- **Pass if**: The chat has the right members and topic.
- **Status**: `untested`
- **Notes**: `teams_add_chat_member` needs admin consent. To find the user id of a person, a model uses `teams_list_chat_members`. Check how it finds a person with no chat yet. Cause if it fails: **tool**.

### TM-10 Create and change an online meeting

- **Prompt**: "Create a Teams meeting for tomorrow at 14:00 with Anna and Tom."
- **Tools**: `teams_create_meeting`, `teams_update_meeting`, `teams_delete_meeting`
- **Preset**: `teams-meetings-write`
- **Pass if**: The meeting has a join link and the attendees.
- **Status**: `untested`
- **Notes**: By design the meeting is on no calendar and nobody gets an invitation. `outlook_create_event` with `online_meeting` is the usual route. Check that a model picks it. Cause: **description**.

### TM-11 Recap a meeting from the transcript

- **Prompt**: "Summarize yesterday's design review and list the action items."
- **Tools**: `teams_list_chats`, `teams_list_meeting_transcripts`, `teams_read_transcript`
- **Preset**: `teams-transcripts`
- **Pass if**: The summary uses the transcript turns with the speakers named.
- **Status**: `untested`
- **Notes**: Needs admin consent. A long transcript comes in pages, so check the paging.

### TM-12 Get the recording of a meeting

- **Prompt**: "Give me the recording of yesterday's meeting."
- **Tools**: `teams_list_meeting_recordings`
- **Preset**: `teams-recordings`
- **Pass if**: The model gets the video or a link that the user can open.
- **Status**: `expected gap`
- **Notes**: Cause: **graph**, by design. The tool returns metadata only. The recording URL opens only with the connector's own token.

### TM-13 Read who attended a meeting

- **Prompt**: "Who came to my 1:1 yesterday, and for how long?"
- **Tools**: `teams_list_chats`, `teams_read_meeting`
- **Preset**: `teams-meetings-write`
- **Pass if**: The answer names the attendees and the time of each.
- **Status**: `untested`
- **Notes**: Graph gives attendance to the organizer only. For a meeting that another person organizes, the status is `not_organizer`. Cause: **graph**.

## SharePoint and OneDrive

### SP-01 Find a file

- **Prompt**: "Find the latest PowerPoint about the Q3 plan that Anna edited."
- **Tools**: `sharepoint_search_files`
- **Preset**: `sharepoint-search`
- **Pass if**: The file is in the first rows. `last_modified_by` names the editor.
- **Status**: `untested`
- **Notes**: Check `file_type`, `modified_after`, and `sort_by` together. The tool has no filter by editor, so the model must read `last_modified_by`. Cause if it fails: **parameter**.

### SP-02 Find a site and search in it

- **Prompt**: "Search only the Legal site for the NDA template."
- **Tools**: `sharepoint_search_sites`, `sharepoint_search_files`
- **Preset**: `sharepoint-sites`
- **Pass if**: The search runs under the site address that the first tool gave.
- **Status**: `untested`

### SP-03 Browse a folder

- **Prompt**: "What is in the Contracts folder on the Legal site, newest first?"
- **Tools**: `sharepoint_list_drives`, `sharepoint_browse_folder`
- **Preset**: `sharepoint-search`
- **Pass if**: The folder list is in the right order.
- **Status**: `untested`

### SP-04 Read a file

- **Prompt**: "Read the contract and tell me the notice period."
- **Tools**: `sharepoint_search_files`, `sharepoint_read_file`
- **Preset**: `sharepoint-read`
- **Pass if**: The answer comes from the content of the file.
- **Status**: `expected gap`
- **Notes**: Test a docx, an xlsx, a pptx, and a pdf, with `convert_to` set to PDF and without it. Graph returns no extracted text, so the result depends on what the client does with the bytes. Cause: **graph**.

### SP-05 Open a sharing link

- **Prompt**: "Summarize this: https://contoso.sharepoint.com/:w:/s/..."
- **Tools**: `sharepoint_resolve_url`, `sharepoint_read_file`
- **Preset**: `sharepoint-write`
- **Pass if**: The link resolves to the file and the model reads it.
- **Status**: `untested`
- **Notes**: `sharepoint-read` lacks `sharepoint_resolve_url`. A read-only user must take `sharepoint-write`. Cause: **preset**.

### SP-06 Organize files

- **Prompt**: "Make a folder 2026 Contracts, then move every signed contract into it."
- **Tools**: `sharepoint_create_folder`, `sharepoint_search_files`, `sharepoint_move_item`, `sharepoint_rename_item`
- **Preset**: `sharepoint-write`
- **Pass if**: The items are in the new folder with the same names. The tool asks first.
- **Status**: `untested`
- **Notes**: The move works inside one drive only. A move to another drive needs `sharepoint_copy_item`, then a delete.

### SP-07 Copy and delete

- **Prompt**: "Copy the template folder to the new project, then delete the old draft."
- **Tools**: `sharepoint_copy_item`, `sharepoint_delete_item`
- **Preset**: `sharepoint-write`
- **Pass if**: The copy ends, and the draft is in the recycle bin.
- **Status**: `untested`
- **Notes**: Microsoft makes the copy after the call returns. Check whether the model can tell when it ends.

### SP-08 Save text as a file

- **Prompt**: "Save these meeting notes as a file in the Notes folder."
- **Tools**: `sharepoint_create_text_file`
- **Preset**: `sharepoint-write`
- **Pass if**: The file is in the folder with the text.
- **Status**: `expected gap`
- **Notes**: Cause: **tool**. It creates new text files only. It cannot replace a file, upload a binary, or create a docx.

### SP-09 Share a file

- **Prompt**: "Give Anna edit access to this file and send me a link."
- **Tools**: `sharepoint_invite`, `sharepoint_create_share_link`
- **Preset**: `sharepoint-share`
- **Pass if**: Anna can edit. The link opens the file.
- **Status**: `untested`
- **Notes**: Check the link scope. A link for anyone is a risk, so check what the tool asks.

### SP-10 Take back access

- **Prompt**: "Stop sharing the contract with Anna."
- **Tools**: none
- **Preset**: none
- **Pass if**: Anna loses access.
- **Status**: `expected gap`
- **Notes**: Cause: **tool**. The description of `sharepoint_invite` says no tool here can take the access back.

## OneNote

### ON-01 Find a notebook or a page

- **Prompt**: "Find my notes from the Acme kickoff."
- **Tools**: `onenote_list_notebooks`, `onenote_list_pages`, `onenote_list_recent_notebooks`
- **Preset**: `onenote-read`
- **Pass if**: The page is found by its title.
- **Status**: `expected gap`
- **Notes**: Cause: **graph**. Graph has no full-text search for OneNote, so a page is found by title only. Check `title_contains` with a word that is only in the body.

### ON-02 Open a notebook from a link

- **Prompt**: "Read this page: https://contoso.sharepoint.com/..."
- **Tools**: `onenote_find_notebook_from_url`, `onenote_list_pages`, `onenote_read_page`
- **Preset**: `onenote-read`
- **Pass if**: The model reaches the page that the link names.
- **Status**: `untested`
- **Notes**: The tool resolves a notebook, not a page. Check how the model finds the page after that.

### ON-03 Read a page with images

- **Prompt**: "What does the whiteboard photo on my planning page show?"
- **Tools**: `onenote_read_page`, `onenote_read_resource`
- **Preset**: `onenote-read`
- **Pass if**: The model gets the image bytes with the real media type.
- **Status**: `untested`

### ON-04 Capture a note

- **Prompt**: "Create a page Weekly sync in my Work section with these three notes."
- **Tools**: `onenote_list_sections`, `onenote_create_page`, `onenote_append_to_page`
- **Preset**: `onenote-write`
- **Pass if**: The page exists with the notes in order.
- **Status**: `untested`

### ON-05 Edit a page

- **Prompt**: "On my planning page, change the date in the second paragraph and add a task list under it."
- **Tools**: `onenote_read_page`, `onenote_edit_page`, `onenote_rename_page`
- **Preset**: `onenote-write`
- **Pass if**: Only the named element changed.
- **Status**: `untested`
- **Notes**: `onenote_edit_page` takes 1 to 20 commands. Test an insert, a replace, and a batch.

### ON-06 Build the structure

- **Prompt**: "Create a notebook Customers with a section for each of these three accounts."
- **Tools**: `onenote_create_notebook`, `onenote_create_section`, `onenote_create_section_group`
- **Preset**: `onenote-write`
- **Pass if**: The tree has the notebook, the sections, and the groups.
- **Status**: `untested`

### ON-07 Copy notebooks, sections, or pages

- **Prompt**: "Copy my Template section into the Customers notebook."
- **Tools**: `onenote_copy_section`, `onenote_get_operation`
- **Preset**: `onenote-write`
- **Pass if**: The operation ends, and the section is in the new place.
- **Status**: `untested`
- **Notes**: The three copy tools refuse a site notebook before they call Graph.

### ON-08 Use a team or site notebook

- **Prompt**: "Add a page to the Platform team's notebook."
- **Tools**: `teams_list_my_teams`, `onenote_list_notebooks`, `onenote_create_page`
- **Preset**: `exact list`
- **Pass if**: The page is in the team notebook. The tool asks first.
- **Status**: `untested`
- **Notes**: Cause: **preset**. No OneNote preset holds `teams_list_my_teams`, and no tool finds the id of a site.

### ON-09 Delete a page

- **Prompt**: "Delete the old draft page."
- **Tools**: `onenote_list_pages`, `onenote_delete_page`
- **Preset**: `onenote-delete`
- **Pass if**: The page is gone. The tool asks first.
- **Status**: `untested`
- **Notes**: Graph keeps no recycle bin for OneNote, so the tool is not reversible.

## Across surfaces

These use cases join two or more surfaces. A handle that one tool returns must open in the next
tool. This is where a break shows first.

### X-01 Prepare for a meeting

- **Prompt**: "I have a customer call at 15:00. Give me the mail thread, the Teams chat, and the files about them."
- **Tools**: `outlook_list_events`, `outlook_read_event`, `outlook_search_mail`, `outlook_read_thread`, `teams_search_messages`, `sharepoint_search_files`
- **Preset**: `exact list`
- **Pass if**: The brief holds the event, the right thread, the right chat messages, and the right files.
- **Status**: `untested`
- **Notes**: Cause of the exact list: **preset**.

### X-02 Follow up after a meeting

- **Prompt**: "From yesterday's transcript, draft a follow-up mail to the attendees and save the notes in OneNote."
- **Tools**: `teams_list_meeting_transcripts`, `teams_read_transcript`, `outlook_draft_mail`, `onenote_create_page`
- **Preset**: `exact list`
- **Pass if**: The draft goes to the attendees. The page holds the action items.
- **Status**: `untested`
- **Notes**: The transcript does not list attendee emails. Check how the model gets the addresses. Cause if it fails: **tool**.

### X-03 Send a SharePoint file by mail

- **Prompt**: "Mail the signed contract from SharePoint to Anna."
- **Tools**: `sharepoint_search_files`, `outlook_draft_mail`, `sharepoint_create_share_link`, `outlook_send_draft`
- **Preset**: `exact list`
- **Pass if**: Anna gets a mail that opens the file.
- **Status**: `expected gap`
- **Notes**: Cause: **tool**. The mail cannot carry the file as an attachment (see OL-MAIL-09). A share link is the workaround.

### X-04 Weekly digest

- **Prompt**: "Give me a digest of my week: meetings, open mail, and unread Teams chats."
- **Tools**: `outlook_list_events`, `outlook_list_mail`, `teams_list_chats`
- **Preset**: `exact list`
- **Pass if**: The three parts are in the answer, and each one matches the source.
- **Status**: `untested`
- **Notes**: Cause of the exact list: **preset**.
