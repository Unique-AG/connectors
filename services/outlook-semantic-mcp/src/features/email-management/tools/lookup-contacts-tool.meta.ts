import { createMeta } from '@unique-ag/mcp-server-module';

export const META = createMeta({
  icon: 'users',
  systemPrompt:
    "Resolves a person's name to one or more real email addresses by searching the Microsoft People directory and recent inbox senders. Use this as a last resort when `os_mcp_search_emails` returns no relevant results and you still need to find a recipient's email address. Do not call this tool first — prefer `os_mcp_search_emails` and only fall back to `os_mcp_lookup_contacts` if that yields nothing.",
  toolFormatInformation: `### Format for contact results
Display each contact on a single line — no headers, no extra blank lines:
**{name}** — {email}
Rules:
- Show at most 15 results. If more were returned, show the first 5 and add a note: "_X more found — try a more specific name._"
- If no contacts are found, tell the user and ask them to provide the email address manually.
Example (3 results):
**Florian Müller** — florian.mueller@acme.com
**Florian Schmidt** — f.schmidt@partner.io
**Florian Weber** — florian.weber@acme.com`,
});
