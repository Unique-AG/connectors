import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'folder',
  systemPrompt:
    'Returns a hierarchical tree of Outlook mail folders. Each folder has an id and displayName. Use folder ids when calling the email search tool to filter results to a specific folder. Call this tool first when the user wants to search emails in a specific folder or asks which folders are available.',
  toolFomatting: `## Folder deep link
  https://outlook.office.com/mail/<FOLDER_ID>
  Rules:
  1. Always use the folder ID in the URL — never use shorthand names like "inbox", "sentitems", etc.
  2. Folder display names (e.g. "Inbox", "My Projects") cannot be used in the URL — only the folder ID works.
  3. Always render folder references as markdown links with the folder's display name as the link text.
     Format: [<FOLDER_DISPLAY_NAME>](https://outlook.office.com/mail/<FOLDER_ID>)
     Examples:
     - [Inbox](https://outlook.office.com/mail/AAMkAGQ3Y2...)
     - [Sent Items](https://outlook.office.com/mail/AAMkAGQ3Y2...)
     - [My Projects](https://outlook.office.com/mail/AAMkAGQ3Y2...)`,
});
