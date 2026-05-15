# Design: Outlook MCP features page + delegated access setup docs

## Problem

The Outlook Semantic MCP docs describe delegated-access *behavior* (scanning,
mode A/B, revocation, search/ingestion semantics) in `faq.md`,
`operator/configuration.md`, and `README.md`, but they do not document how to
*set up* delegated access so the MCP can detect it. Specifically missing:

- How an Exchange admin grants Full Access (Read & Manage) to a user so the
  delegate becomes detectable by the discovery scan.
- How a user can share folders to another user without Exchange admin
  involvement.
- The Outlook gotcha: the sharing user must right-click the mailbox root in
  Outlook desktop and grant the delegate visibility on the root mailbox,
  otherwise `GET /users/{email}/mailFolders` returns 404 and the MCP cannot
  enumerate the shared folders — even though Outlook desktop still shows them
  (Outlook uses internal APIs that are not publicly accessible).
- An explicit statement of what sharing configurations the MCP supports — and
  what it does **not** support (e.g. shared inboxes that have not been
  configured as normal mailboxes with delegated access).
- How a shared inbox can be ingested today: it must be configured as a normal
  inbox, every user who needs access must have delegated access to it, and
  someone must sign into the MCP using the shared-inbox account itself.

In addition, the docs lack a single feature-overview layer. The main README
lists features as bullets, `tools.md` describes each tool, and
`configuration.md` describes env vars — but there is no doc that says, for each
user-facing feature, "this is what's supported, this is what's not, and this
is what you need to set up." The delegated-access content described above fits
naturally into that layer.

## Solution

### Overview

Create `services/outlook-semantic-mcp/docs/technical/features.md`, a new
feature-catalog page that sits between the README bullet list and the per-tool
`tools.md` reference. The page covers five features:

1. Email Search
2. Draft Creation
3. Contact Resolution
4. Mailbox & Folder Listing
5. Delegated Access

Each feature has three subsections — *What's supported*, *What's not
supported*, and *Setup* (omitted when no setup is required). The first four
features get short treatments (a few bullets each) that link out to
`tools.md` and `configuration.md`. Delegated Access gets the substantive
treatment: the three supported setup paths, the Outlook root-mailbox
visibility gotcha, the shared-inbox-as-normal-inbox workaround, the
unsupported configurations list, and a recap of detection / search /
ingestion behavior per mode (cross-linking to existing FAQ entries rather
than duplicating them).

Add a single new FAQ entry — "How do I set up delegated access?" — that
points readers to the new features page section. The existing
"Shared Inbox & Delegated Access" FAQ entries are unchanged: they answer
behavior questions, not setup questions, and the split is the right one.

Wire the new page into the docs index in three places: the main
`docs/README.md` Features section (link from the "Delegated Mailbox Access"
bullet), `docs/technical/README.md` documentation table, and a cross-link
from the FAQ section heading.

### Architecture

**File layout.** One new file plus four small edits:

- `services/outlook-semantic-mcp/docs/technical/features.md` *(new)*
- `services/outlook-semantic-mcp/docs/technical/README.md` — add row to doc table
- `services/outlook-semantic-mcp/docs/README.md` — add link from delegated
  access bullet
- `services/outlook-semantic-mcp/docs/faq.md` — add setup FAQ entry pointing
  to the new page
- `services/outlook-semantic-mcp/docs/operator/configuration.md` — (optional)
  add a "see the features page for end-to-end setup" cross-link at the top of
  the `DELEGATED_ACCESS_SCAN` section

**`features.md` page structure.**

- Page header: confluence-page-id placeholder + `# Outlook Semantic MCP – Features`.
  Brief intro: this page describes user-facing features, what's supported,
  what's not, and any setup required. For per-tool input/output reference, see
  `tools.md`; for env vars, see `operator/configuration.md`.
- `## Email Search`
  - *What's supported* — semantic + KQL parallel in Mode A; KQL-only in Mode B;
    folder filtering in Mode A only; sync warning while full sync in progress.
  - *What's not supported* — calendar/tasks/files, folder filtering in Mode B.
  - No setup subsection.
  - Link to `tools.md#search_emails`.
- `## Draft Creation`
  - *Supported* — create drafts in user's Drafts folder, with subject/body/
    recipients/attachments; draft is not sent automatically (response includes
    a `webLink`).
  - *Not supported* — sending email directly from the MCP, drafting on behalf
    of another mailbox.
  - No setup.
  - Link to `tools.md#create_draft_email`.
- `## Contact Resolution`
  - *Supported* — lookup against the user's Microsoft contacts directory.
  - *Not supported* — org-wide directory queries beyond what
    `People.Read` exposes.
  - No setup.
  - Link to `tools.md#lookup_contacts`.
- `## Mailbox & Folder Listing`
  - *Supported* — list own and delegated mailboxes and their folder trees in
    Mode A; folder IDs feed into `search_emails` filter conditions.
  - *Not supported* — folder filtering in Mode B (Graph Search API limitation).
  - No setup.
  - Link to `tools.md#list_mailboxes_and_directories`.
- `## Delegated Access` *(the substantive section)*
  - Intro paragraph: what delegated access means here (Microsoft 365 Exchange
    delegation between two MCP-connected users), and a one-line summary that
    the MCP only detects access between mutually connected users.
  - `### What's supported` — three configurations:
    1. Exchange admin grants **Full Access (Read & Manage)** to a user on
       another user's mailbox.
    2. A user shares specific folders to another user from Outlook desktop
       (without Exchange admin involvement), with the root-mailbox visibility
       step described under Setup.
    3. A shared inbox configured as a normal mailbox where every user who needs
       access has delegated access to it, and someone signs into the MCP as
       the shared-inbox account itself so its emails can be ingested.
  - `### What's not supported` — explicit list:
    - Microsoft 365 shared mailboxes that are not configured as a normal
      mailbox with delegated access (no other shared-mailbox configurations
      are detected).
    - Application-permission based access (the MCP uses delegated permissions
      only — see existing FAQ).
    - Any access path that does not show up via Graph's `/users/{email}/messages`
      (full-access check) or `/users/{email}/mailFolders` (folder-level check).
    - Detecting delegated access for users who have not connected the MCP —
      both the owner and the delegate must be connected.
  - `### Setup`
    - `#### 1. Exchange admin grants Full Access`
      - Option A: Exchange admin center GUI — steps: open admin center,
        Recipients → Mailboxes, select target mailbox, Mailbox delegation,
        add user(s) to Full Access. Screenshot-style numbered steps, no
        actual screenshots required.
      - Option B: PowerShell — `Add-MailboxPermission` example with
        `-AccessRights FullAccess -InheritanceType All`.
      - Detection note: once granted, the delegate is detected on the next
        `DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE` run (default every 12 h).
    - `#### 2. User shares specific folders (no admin needed)`
      - Steps in Outlook desktop: right-click the folder → Properties →
        Permissions → Add user → set permission level → OK.
      - **Critical gotcha #1 — mailbox root visibility** — call it out in a
        `> **Important**` blockquote: *Right-click on the mailbox name at the
        top of the folder tree (the owner's email/display name, not the
        Inbox folder), choose Sharing Permissions or Folder Permissions,
        add the delegate, and grant a Folder visible / non-editing
        permission level on the root mailbox.*
      - Why: without this, `GET /users/{email}/mailFolders` returns 404 for
        the delegate because Graph cannot enumerate the mailbox root. Outlook
        desktop still shows the shared folders because it uses internal MAPI
        APIs that bypass Graph — so the user may think the sharing "worked"
        when in fact the MCP cannot see it.
      - **Critical gotcha #2 — full path visibility for nested folders** —
        call it out in a second `> **Important**` blockquote: *Every folder
        on the path from the mailbox root to the shared folder must also
        have "Folder visible" toggled on for the delegate. If the owner
        shares `Inbox → Clients → Contoso → Invoices`, then `Inbox`,
        `Clients`, and `Contoso` must each have "Folder visible" granted to
        the delegate, in addition to whatever read permission is set on
        `Invoices`. Without this, Graph cannot traverse the folder
        hierarchy to reach `Invoices` and the folder is invisible to the
        MCP even though Outlook desktop may still show it.*
      - Why: the Graph `mailFolders` traversal walks the parent chain — any
        parent folder that is not at least Folder-visible to the delegate
        breaks the chain. Outlook desktop uses MAPI shortcuts that do not
        require an unbroken visibility chain, which is why this is a
        silent failure mode that only surfaces in the MCP.
      - Detection note: discovery picks up the folder-level access on the next
        `DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE` run (default every 4 h),
        and only in `granularAccess` mode — `fullAccessOnly` mode does not
        detect folder-level shares.
    - `#### 3. Shared inbox configured as a normal inbox`
      - Steps: in Microsoft 365 admin center, configure the shared mailbox
        with a sign-in-eligible password (or grant access via Exchange admin
        center as above), grant Full Access to each user who needs it, then
        connect the MCP using the shared-inbox account itself so its emails
        are ingested into the Unique knowledge base.
      - Note: this is the *only* way to make a shared inbox searchable today.
        Without an MCP login for the shared inbox, no ingestion occurs and no
        delegated relationships are recorded against it.
  - `### Behavior` — short subsection that recaps and links out:
    - Detection: only between mutually connected users; configured via
      `DELEGATED_ACCESS_SCAN` (link to `configuration.md`).
    - Mode A (`MicrosoftGraphAndUniqueApi`): semantic search uses ingested
      data only; KQL via Graph runs in parallel; folder filtering supported
      when `granularAccess`. Link to existing FAQ "What happens with delegated
      access?".
    - Mode B (`MicrosoftGraph`): Graph KQL search only; **full access required**
      (folder-level not supported in Mode B due to API rate-limit cost).
    - Ingestion: only the connected user's own inbox is ingested. Delegated
      mailboxes are searchable through the owner's already-ingested scope.
      Shared inboxes that have not been connected as their own MCP account are
      not ingested.

**FAQ entry.** Insert a new entry at the top of the existing
"Shared Inbox & Delegated Access" section, *before* "Who has access to a
shared inbox?":

> ### How do I set up delegated access?
>
> **Answer:** Delegated access setup happens in Microsoft 365, not in the
> MCP. The MCP supports three configurations: Exchange admin grants Full
> Access, a user shares specific folders via Outlook desktop (with a required
> root-mailbox visibility step), or a shared inbox is configured as a normal
> mailbox and connected to the MCP. See
> [Features — Delegated Access — Setup](./technical/features.md#Setup) for
> step-by-step instructions and the Outlook root-mailbox visibility gotcha.

**Cross-links.**

- `docs/README.md` — under the "Delegated Mailbox Access" bullet add
  "See [Features — Delegated Access](./technical/features.md#Delegated-Access)
  for supported configurations and setup."
- `docs/technical/README.md` — add a row to the doc table for `features.md`
  with description "User-facing features, what's supported, what's not, and
  setup steps (including delegated access)".
- `docs/operator/configuration.md` — optional: add one line at the top of the
  `DELEGATED_ACCESS_SCAN` section reading
  "For step-by-step Microsoft 365 setup, see
  [Features — Delegated Access — Setup](../technical/features.md#Setup)."

### Error Handling

Documentation change only — no runtime error handling.

### Testing Strategy

Documentation change only — no tests. Manual verification:

- Render the new page locally (or in Confluence preview) and confirm all
  intra-doc anchor links resolve.
- Confirm `confluence-page-id`/`confluence-space-key` HTML comments are
  present at the top of the new file. Use a placeholder
  `<!-- confluence-page-id: TBD -->` and `<!-- confluence-space-key: PUBDOC -->`;
  the page ID will be assigned when the page is first published — match the
  pattern used by the other docs in this directory.

## Out of Scope

- Rewriting the existing FAQ "Shared Inbox & Delegated Access" entries. They
  answer behavior questions ("what happens with delegated access?", "who has
  access?", "what happens on revocation?") and are correct as written. Adding
  one setup-pointer FAQ entry is enough; the rest stay.
- Adding features-page coverage for Subscription Management, Email Sync, or
  Live Catch-Up. These are infrastructure concerns documented in
  `architecture.md` and `flows.md`; a feature-overview duplicate would be
  noise.
- Changes to `tools.md` or `configuration.md` beyond the optional one-line
  cross-link in `configuration.md`.
- Diagrams or screenshots. Numbered written steps match the existing
  `operator/authentication.md` style — adding images is out of scope.
- Any code changes.

## Tasks

1. **Create `technical/features.md`** — New file with confluence page-id
   placeholder header and a brief intro. No section bodies yet; just the H2
   skeleton for the five features so the structure is in place.

2. **Write the short feature sections** — Fill in *What's supported* /
   *What's not supported* sections for Email Search, Draft Creation, Contact
   Resolution, and Mailbox & Folder Listing, each with a link out to the
   relevant `tools.md` anchor. Keep each section to a handful of bullets.

3. **Write the Delegated Access section** — Intro paragraph; supported
   configurations list; unsupported configurations list; setup subsections for
   each of the three supported paths (Exchange admin Full Access via GUI +
   PowerShell, user folder sharing in Outlook desktop with the root-mailbox
   visibility gotcha called out in a blockquote, shared-inbox-as-normal-inbox
   workaround); short behavior recap subsection with links to the existing
   FAQ and configuration entries.

4. **Add the FAQ entry** — Insert "How do I set up delegated access?" at the
   top of the "Shared Inbox & Delegated Access" section in `faq.md`, pointing
   to `technical/features.md#Setup`. Update the FAQ table of contents anchor
   list accordingly.

5. **Wire cross-links** — Add `features.md` row to
   `technical/README.md` doc table; add a "See Features — Delegated Access"
   link under the Delegated Mailbox Access bullet in the main `docs/README.md`;
   optionally add a one-line setup-cross-link at the top of the
   `DELEGATED_ACCESS_SCAN` section in `operator/configuration.md`.

6. **Verify** — Render the new page (or open in editor preview) and confirm
   all intra-doc anchors resolve; confirm the confluence-page-id placeholder
   matches the pattern in the other docs in the directory.
