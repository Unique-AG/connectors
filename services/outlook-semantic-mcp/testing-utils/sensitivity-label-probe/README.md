# Sensitivity label probe

How Microsoft Graph v1.0 exposes a message's sensitivity, for `EXCLUDED_SENSITIVITY_LABELS`.
Results: [`results/2026-11-26.json`](results/2026-11-26.json). They hold label ids and names only,
no subject, body or address.

Two markers exist, and both are read with
`$expand=singleValueExtendedProperties($filter=id eq '<id>' or id eq '<id>')`:

- the Purview sensitivity label, `String {00020386-0000-0000-C000-000000000046} Name msip_labels`.
  Its value is `MSIP_Label_<label id>_Enabled=True;...;MSIP_Label_<label id>_Name=<name>;...`,
  one group per label. A sublabel carries only its own name.
- the legacy Outlook flag, `Integer 0x0036` (PidTagSensitivity): 0 normal, 1 personal, 2 private,
  3 confidential.

## Findings, 2026-11-26

- Both properties are readable on received and sent mail. Unlabelled mail has the legacy flag `0`
  and the Purview property absent or empty.
- `internetMessageHeaders` (`msip_labels`, `Sensitivity`) holds values for received mail only, so
  the headers themselves cannot cover sent mail or drafts.
- **A `$search` returns the requested properties only when `internetMessageHeaders` is in its
  `$select`.** Without it, mailbox-wide and folder-scoped searches alike ignore the `$expand`
  filter and return `Binary 0xf03` and the normalized subject instead. With it, both properties
  come back in full, in a `$batch` too, and the `@odata.nextLink` keeps both. This is not
  documented; a filter built on it must drop a hit whose properties are missing rather than keep it.
- A single-message GET returns both properties in full, whatever its `$select`.
- A listing without `internetMessageHeaders` in its `$select` cuts the Purview value to its first
  255 characters (label id kept, name lost); with it, the value is full.
- `$filter` on the legacy flag works with the cast form,
  `singleValueExtendedProperties/any(ep: ep/id eq 'Integer 0x0036' and cast(ep/value, Edm.Int32) ne 0)`,
  but Graph rejects `$filter` together with `$search` (400 `SearchWithFilter`), so it cannot
  narrow a search.

## Requests

Run in Graph Explorer as a test-tenant user with mail in Inbox and Sent Items carrying a Purview
label and the legacy flag. Graph Explorer flags `{...}` as a placeholder; the request still runs.

```http
GET /me/mailFolders/inbox/messages?$top=50&$select=subject,isDraft,internetMessageHeaders&$expand=singleValueExtendedProperties($filter=id eq 'String {00020386-0000-0000-C000-000000000046} Name msip_labels' or id eq 'Integer 0x0036')
GET /me/messages?$top=50&$select=subject,isDraft,parentFolderId&$filter=singleValueExtendedProperties/any(ep: ep/id eq 'Integer 0x0036' and cast(ep/value, Edm.Int32) ne 0)&$expand=<as above>
GET /me/messages/{id}?$select=subject,internetMessageHeaders&$expand=<as above>
GET /me/messages?$search="Confidential"&$top=25&$select=subject,isDraft,parentFolderId,internetMessageHeaders&$expand=<as above>
POST /$batch  with each $search on /users/{id}/messages and /users/{id}/mailFolders/{inbox|sentitems}/messages,
              with search_emails' $select, with and without internetMessageHeaders; its @odata.nextLink;
              a $search plus the legacy $filter; and GETs of one message with the $expand
```
