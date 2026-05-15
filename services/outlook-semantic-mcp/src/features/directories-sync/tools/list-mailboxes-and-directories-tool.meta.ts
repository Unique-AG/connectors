import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'folder',
  systemPrompt:
    "Returns Outlook mail folders grouped by mailbox. Each mailbox has an email, displayName, and isOwn flag, plus a folders array. A mailbox with isOwn: true is the user's own primary mailbox; mailboxes with isOwn: false are delegated (shared) mailboxes the user has been granted access to. Each folder has an id, displayName, canReadContent flag, and children array (recursive — folders can be nested). For own mailboxes all folders are readable. For delegated mailboxes, canReadContent: true means the folder was explicitly shared and can be searched; canReadContent: false means the folder is only present as a structural parent in the tree and cannot be searched. Only pass folder ids with canReadContent: true to the email search tool.",
  toolFormatInformation: `## Rendering rules
  1. Render each mailbox as an H1 heading: "DisplayName (email) — Own Mailbox" or "— Delegated". Omit whichever of displayName/email is null.
  2. Always render every folder as a markdown link: [DisplayName](https://outlook.office.com/mail/<FOLDER_ID>).
  3. For folders with canReadContent: false, append a 🔒 icon after the link to signal the folder is not searchable.
  4. Nest children with indentation regardless of canReadContent.
  5. Always use the opaque folder ID in the URL — never shorthand names like "inbox" or "sentitems".

  Example:
  # John Doe (john.doe@contoso.com) — Own Mailbox
  - [Inbox](https://outlook.office.com/mail/AAMkAGQ3Y2...)
    - [Team Updates](https://outlook.office.com/mail/BBMkAGQ3Y2...)
  - [Sent Items](https://outlook.office.com/mail/CCMkAGQ3Y2...)
  - [Drafts](https://outlook.office.com/mail/DDMkAGQ3Y2...)

  # Jane Smith (jane.smith@contoso.com) — Delegated
  - [Inbox](https://outlook.office.com/mail/EEMkAGQ3Y2...) 🔒
    - [Team Updates](https://outlook.office.com/mail/BBMkAGQ3Y2...)
  - [Projects](https://outlook.office.com/mail/FFMkAGQ3Y2...)
    - [Q2 Planning](https://outlook.office.com/mail/GGMkAGQ3Y2...)`,
});
