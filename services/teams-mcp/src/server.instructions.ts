export const serverInstructions = `
## Tool Selection Guidelines for Outlook MCP

### Reading Emails
- Use **list_mails** for quick overview of recent emails in a folder
- Use **search_email** for finding specific emails by criteria (sender, subject, date range, etc.)
- Use **get_mail_message** for full email details when user wants to read/analyze a specific email
- Use **list_mail_folder_messages** when user wants emails from a specific folder (vs default inbox)

### Managing Folders
- Use **list_mail_folders** to show available folders or when user asks about folder structure
- Set **includeChildFolders: true** only if user specifically needs subfolder information

### Email Actions
- Use **create_draft_email** when user wants to compose but not send immediately
- Use **send_mail** for immediate email sending
- Use **move_mail_message** to organize emails into different folders
- Use **delete_mail_message** to remove unwanted emails

### Search Strategy
- Use **search_email** instead of **list_mails** when user provides any search criteria
- Combine multiple filters (from, subject, date range, etc.) in a single search_email call
- Use **orderBy** and **orderDirection** only when NOT using text search (query parameter)

## Formatting Guidelines for Outlook MCP

### Email List Display
When showing multiple emails (from list_mails, search_email, or list_mail_folder_messages), format each email like this:
\`\`\`markdown
- **[SUBJECT](mailto:FROM_ADDRESS)** 
  From: **FROM_NAME** <FROM_ADDRESS> • [RECEIVED_DATE]
  [PREVIEW - truncated to ~120 chars]
  Status: [READ_EMOJI][ATTACHMENT_EMOJI]
  <details><summary>Meta</summary>
  
  | Field | Value |
  |-------|-------|
  | Message ID | \`MESSAGE_ID\` |
  | Importance | [IMPORTANCE] |
  | Has Attachments | [true/false] |
  | Folder | [FOLDER_NAME] |
  | Folder ID | [FOLDER_ID] |
  </details>
\`\`\`

**Status Emoji Guide:**
- Read status: 📖 Read, 📧 Unread
- Attachments: 📎 Has attachments, ⚬ No attachments

Sort emails by: receivedAt (newest first), then by importance (high to low), then by read status (unread first).

### Individual Email Display
When showing a single email (from get_mail_message), format like this:
\`\`\`markdown
# 📧 [SUBJECT]

**From:** [FROM_NAME] <[FROM_ADDRESS]>  
**To:** [TO_RECIPIENTS]  
**Date:** [RECEIVED_DATE] • **Sent:** [SENT_DATE]  
**Status:** [READ_STATUS]

[ATTACHMENT_SECTION if hasAttachments]

---

[EMAIL_BODY]

<details><summary>Technical Details</summary>

| Field | Value |
|-------|-------|
| Message ID | \`[MESSAGE_ID]\` |
| Internet Message ID | \`[INTERNET_MESSAGE_ID]\` |
| Conversation ID | \`[CONVERSATION_ID]\` |
| Parent Folder ID | \`[PARENT_FOLDER_ID]\` |
| Web Link | [WEB_LINK] |
| Is Draft | [IS_DRAFT] |

</details>
\`\`\`

### Folder List Display  
When showing folders (from list_mail_folders), format like this:
\`\`\`markdown
- **[FOLDER_NAME]** 
  📧 [UNREAD_COUNT] unread • 📁 [TOTAL_COUNT] total
  <details><summary>Details</summary>
  
  | Field | Value |
  |-------|-------|
  | Folder ID | \`[FOLDER_ID]\` |
  | Child Folders | [CHILD_FOLDER_COUNT] |
  | Parent ID | \`[PARENT_FOLDER_ID]\` |
  </details>
\`\`\`

### Search Results Display
When showing search results, always include the search criteria summary:
\`\`\`markdown
## 🔍 Search Results ([COUNT] emails found)

**Search Criteria:**
- Query: "[QUERY]" 
- Folder: [FOLDER_NAME or "All folders"]
- From: [FROM_FILTER]
- Subject contains: "[SUBJECT_FILTER]"
- Date range: [DATE_FROM] to [DATE_TO]
- Status: [READ_FILTER] • Attachments: [ATTACHMENT_FILTER] • Importance: [IMPORTANCE_FILTER]

[EMAIL_LIST using standard email format above]
\`\`\`

### Action Results Display
For email actions (send, create draft, move, delete), format confirmations like this:
\`\`\`markdown
✅ **[ACTION] Successful**

[DETAILS based on action type]

[WEB_LINK if available for viewing in Outlook]
\`\`\`

### Date Formatting
- Use relative dates when recent: "2 hours ago", "Yesterday", "3 days ago" 
- Use absolute dates for older emails: "Jan 15, 2024"
- Always show time for today's emails: "Today 2:30 PM"

### Content Truncation
- Email previews: max 120 characters, end with "..."
- Subject lines: max 80 characters in lists, full length in individual display
- From names: max 30 characters in lists, full length in individual display

### Error Handling
When tools return errors, format like this:
\`\`\`markdown
❌ **Error: [ERROR_TYPE]**

[USER_FRIENDLY_ERROR_MESSAGE]

<details><summary>Technical Details</summary>
[TECHNICAL_ERROR_INFO if helpful]
</details>
\`\`\`
`;
