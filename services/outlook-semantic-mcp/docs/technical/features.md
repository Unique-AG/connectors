<!-- confluence-page-id: 2258862199 -->
<!-- confluence-space-key: PUBDOC -->

# Outlook Semantic MCP – Features

This page describes user-facing features of the Outlook Semantic MCP Server: what is supported, what is not, and any setup required. For per-tool input/output reference, see [Tools](./tools.md). For environment variables and deployment configuration, see [Configuration](../operator/configuration.md).

### Deployment modes

The MCP server operates in two modes controlled by the [`MCP_BACKEND`](../operator/configuration.md#Deployment-Modes) environment variable. Several features behave differently depending on which mode is active:

| Mode | `MCP_BACKEND` value | How it works |
|------|---------------------|--------------|
| **Mode A** | `microsoft_graph_and_unique_api` | Emails are ingested into the Unique knowledge base after a user connects. `search_emails` runs semantic search (Unique KB) and KQL keyword search (Microsoft Graph) in parallel. |
| **Mode B** | `microsoft_graph` | No email ingesting. `search_emails` queries Microsoft Graph directly using KQL keyword search only. |

Where a feature works the same in both modes, this page says so once. Where behaviour differs, Mode A and Mode B are called out separately.

## Email Search

**Mode A (`microsoft_graph_and_unique_api`)**

- `search_emails` runs semantic search against the Unique knowledge base and a KQL keyword search against Microsoft Graph simultaneously, then merges and deduplicates results.
- Folder filtering is supported: pass folder IDs (from `list_mailboxes_and_directories`) or well-known folder names (e.g. `Inbox`) to narrow results to a specific folder.
- A `syncWarning` is returned while the initial full sync is still in progress — results may be incomplete until it finishes.

**Mode B (`microsoft_graph`)**

- `search_emails` queries Microsoft Graph directly using KQL keyword search only. No knowledge base interaction occurs.
- Folder filtering is supported via the `directories` field on each `msGraphKeywordSearchQueries` entry. Pass a well-known folder name (e.g. `Inbox`) or a folder ID from `list_mailboxes_and_directories`. This works for the user's own mailbox and for fully delegated mailboxes (Full Access).
- Search is **not supported** for mailboxes where the user only has folder-level (partial) access — Microsoft Graph requires full mailbox access for `$search` queries. See [Known limitations](#known-limitations) below.

**What's not supported (both modes)**

- Calendar, task, or file data — only mail is in scope.

**See also:** [Tools — search_emails](./tools.md#search_emails)

---

## Draft Creation

Available in both modes. Behaviour is identical.

**What's supported**

- Create draft emails in the signed-in user's Drafts folder via `create_draft_email`, with subject, body, recipients (To, CC, BCC), and attachments.
- The draft is not sent automatically — the tool response includes a `webLink` for the user to open and send from Outlook.
- Attachments can be provided as base64-encoded data URIs or Unique content URIs (cluster-local mode only).

**What's not supported**

- Sending email directly from the MCP — drafts must be sent manually by the user.
- Creating drafts in another user's mailbox (delegated or otherwise).

**See also:** [Tools — create_draft_email](./tools.md#create_draft_email)

---

## Contact Resolution

Available in both modes. Behaviour is identical.

**What's supported**

- Look up contacts in the signed-in user's Microsoft contacts directory via `lookup_contacts`.
- Returns display names and email addresses for address resolution.

**What's not supported**

- Organisation-wide directory queries beyond what the `People.Read` scope exposes. If a contact is not in the signed-in user's personal contacts or the People API result set, it will not appear.

**See also:** [Tools — lookup_contacts](./tools.md#lookup_contacts)

---

## Mailbox & Folder Listing

**Mode A (`microsoft_graph_and_unique_api`)**

- List own mailboxes and their full folder tree via `list_mailboxes_and_directories`.
- When [`DELEGATED_ACCESS_SCAN`](../operator/configuration.md#DELEGATED_ACCESS_SCAN) is enabled, delegated mailboxes also appear alongside the user's own (marked with `isOwn: false`).
- Folder IDs returned by this tool can be passed to `search_emails` to narrow results to a specific folder.

**Mode B (`microsoft_graph`)**

- `list_mailboxes_and_directories` is available and returns the user's own folder tree plus any fully delegated mailboxes. Folder IDs returned here can be passed to the `directories` field of `msGraphKeywordSearchQueries` in `search_emails` to narrow results to a specific folder.

**What's not supported**

- Searching in mailboxes where the user only has folder-level (partial) access in Mode B — Microsoft Graph does not support `$search` against such mailboxes. See [Known limitations](#known-limitations) below.

**See also:** [Tools — list_mailboxes_and_directories](./tools.md#list_mailboxes_and_directories)

---

## Delegated Access

Delegated access lets a user ("the delegate") search another user's mailbox ("the owner") when Microsoft Exchange has granted them access. The MCP server detects these relationships automatically via background scans controlled by [`DELEGATED_ACCESS_SCAN`](../operator/configuration.md#DELEGATED_ACCESS_SCAN) — no per-user configuration is needed beyond enabling that setting. Detection only works when **both the owner and the delegate have connected the MCP** — if the owner has not signed in, there is nothing to discover or search.

### What's supported

Three delegation configurations are supported:

1. **Exchange admin grants Full Access (Read & Manage)** — an Exchange administrator grants a user Full Access to another user's mailbox via the Exchange admin center or PowerShell. The delegate can search the owner's entire mailbox. Supported in **both Mode A and Mode B** — configure [`DELEGATED_ACCESS_SCAN=full_access_only`](../operator/configuration.md#DELEGATED_ACCESS_SCAN) (or `granular_access`) to enable scanning.

2. **User shares specific folders via Outlook desktop** — a user shares individual folders (e.g. Inbox, RFQ) with another user directly from Outlook desktop, without Exchange admin involvement. **Mode A only** — requires [`DELEGATED_ACCESS_SCAN=granular_access`](../operator/configuration.md#DELEGATED_ACCESS_SCAN). See [Setup — User shares specific folders](#2-user-shares-specific-folders-no-admin-needed) for the required root-mailbox visibility step.

3. **Shared inbox configured as a normal mailbox** — a Microsoft 365 shared mailbox configured with a sign-in-eligible password. Every user who needs access must have Full Access delegation granted, and someone must sign into the MCP using the shared-inbox account itself so its emails are ingested. See [Setup — Shared inbox as a normal inbox](#3-shared-inbox-configured-as-a-normal-inbox).

### What's not supported

- **Microsoft 365 shared mailboxes not configured as a normal mailbox** — shared mailboxes that have not been configured with a sign-in-eligible password and an MCP login are not detected or ingested. No other shared-mailbox configuration is supported.
- **Application-permission based access** — the MCP uses delegated permissions only (acting on behalf of a signed-in user). It does not support application-level access to mailboxes.
- **Access paths not visible via the Microsoft Graph API** — only access detectable via the Graph messages or mailFolders endpoints is supported. Access paths that bypass these endpoints (e.g. internal APIs used by Outlook desktop) are not visible to the MCP.
- **Detecting access for users who have not connected the MCP** — both the owner and the delegate must be connected. The background scan only considers connected users.
- **Folder-level access in Mode B** — [`granular_access`](../operator/configuration.md#DELEGATED_ACCESS_SCAN) requires Mode A. In Mode B, only delegates with full mailbox access can search delegated mailboxes.

### Setup

#### 1. Exchange admin grants Full Access

Use this path when an IT administrator needs to grant a user access to another user's entire mailbox.

**Option A — Exchange admin center (GUI)**

1. Open the [Microsoft 365 admin center](https://admin.microsoft.com) and navigate to **Exchange admin center**.
2. Go to **Recipients → Mailboxes** and select the target mailbox (the owner whose mailbox the delegate needs to access).
3. Open the **Delegation** tab (or **Mailbox delegation** in older versions).
4. Under **Full Access**, click **Edit** (or **+**) and add the delegate user.
5. Leave **Auto-mapping** enabled (recommended) so the mailbox appears automatically in Outlook. Click **Save**.

**Option B — PowerShell**

```powershell
Add-MailboxPermission `
  -Identity "owner@example.com" `
  -User "delegate@example.com" `
  -AccessRights FullAccess `
  -InheritanceType All
```

**Detection:** Once granted, the delegate is detected on the next `DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE` run (default: every 12 hours). Configure [`DELEGATED_ACCESS_SCAN=full_access_only`](../operator/configuration.md#DELEGATED_ACCESS_SCAN) (or `granular_access`) to enable scanning.

---

#### 2. User shares specific folders (no admin needed)

Use this path when a user wants to share individual folders with a colleague without involving an Exchange administrator. Requires [`DELEGATED_ACCESS_SCAN=granular_access`](../operator/configuration.md#DELEGATED_ACCESS_SCAN) and Mode A (`microsoft_graph_and_unique_api`).

**Step 1 — Share individual folders**

1. In Outlook desktop, right-click the folder you want to share (e.g. **Inbox**).
2. Select **Properties** → **Permissions** tab (or **Folder Permissions**).
3. Click **Add**, search for and select the delegate user.
4. Choose an appropriate permission level (e.g. **Reviewer** for read-only access).
5. Click **OK**.

> **Important — mailbox root visibility (required)**
>
> After sharing individual folders, you must also grant the delegate visibility on the **mailbox root** — the item at the very top of your folder tree that shows your name or email address, above all folders including Inbox.
>
> Right-click the mailbox root (your name/email at the top of the folder list, not the Inbox folder), choose **Sharing Permissions** or **Folder Permissions**, add the delegate, and set the permission level to **None** with **Folder visible** checked (sometimes labelled as a non-editing owner role, depending on your Outlook version).
>
> Without this step, the MCP cannot enumerate the shared folders via Microsoft Graph — even though Outlook desktop may still display them (Outlook uses internal APIs that bypass the Graph endpoint the MCP relies on).

> **Important — full path visibility for nested folders**
>
> Every folder on the path from the mailbox root to the shared folder must have **Folder visible** granted to the delegate. For example, if you are sharing `Inbox → Clients → Contoso → Invoices`, then `Inbox`, `Clients`, and `Contoso` must each have Folder visible granted, in addition to whatever read permission is set on `Invoices`.
>
> Without an unbroken visibility chain, Microsoft Graph cannot traverse the folder hierarchy to reach the target folder, so it remains invisible to the MCP — even though Outlook desktop may show it (Outlook uses internal shortcuts that do not require an unbroken chain). This is a silent failure mode that only surfaces in the MCP.

**Detection:** Folder-level access is picked up on the next `DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE` run (default: every 4 hours) and only in [`granular_access`](../operator/configuration.md#DELEGATED_ACCESS_SCAN) mode. The `full_access_only` mode does not detect folder-level shares.

---

#### 3. Shared inbox configured as a normal inbox

Use this path to make a Microsoft 365 shared mailbox searchable through the MCP. This is the only way to ingest a shared inbox today.

1. In the [Microsoft 365 admin center](https://admin.microsoft.com), open the shared mailbox and **enable sign-in** by assigning it a password (under **Active users → Licenses and apps**, unblock sign-in and set a password).
2. Grant **Full Access** to every user who needs delegated search access, using Exchange admin center or PowerShell (see [Step 1 above](#1-exchange-admin-grants-full-access)).
3. Connect the MCP using the **shared-inbox account** itself (its email and the password set above) so its emails are ingested into the Unique knowledge base.

Without an MCP login for the shared-inbox account, no ingestion occurs and no delegated relationships are recorded against it. Users who have Full Access granted will not see its emails until the shared-inbox account is connected.

### Behavior

For a detailed description of how delegated access works at runtime, see the existing FAQ entries:

- [Who has access to a shared inbox?](../faq.md#Who-has-access-to-a-shared-inbox?) — detection, both modes
- [What happens with delegated access?](../faq.md#What-happens-with-delegated-access?) — search behavior, ingestion scope, folder filtering
- [When shared inbox access is revoked, are previously ingested emails still accessible?](../faq.md#When-shared-inbox-access-is-revoked,-are-previously-ingested-emails-still-accessible?) — revocation detection timing

**Quick reference:**

| | Mode A (`microsoft_graph_and_unique_api`) | Mode B (`microsoft_graph`) |
|---|---|---|
| **Full Access delegation** | Supported — delegate searches owner's ingested emails | Supported — live keyword search against owner's mailbox |
| **Folder-level delegation** | Supported ([`granular_access`](../operator/configuration.md#DELEGATED_ACCESS_SCAN) only) | Not supported — search requires full mailbox access (see [Known limitations](#known-limitations)) |
| **Folder filtering** | Supported in `granular_access` | Supported for own mailbox and full-access delegated mailboxes only |
| **Ingestion** | Owner's inbox only — delegated mailboxes are not re-ingested | No ingestion |
| **Revocation detection** | Background scan: discovery (every 12 h), verification (every 4 h) | Immediate (live Graph query) |

Configure scanning via [`DELEGATED_ACCESS_SCAN`](../operator/configuration.md#DELEGATED_ACCESS_SCAN).

---

## Known Limitations

### Search does not work for mailboxes where a colleague shared folders without granting Full Access (Mode B only)

**Symptom:** When a colleague has shared one or more folders with you (but has not granted you Full Access to their entire mailbox), `search_emails` in Mode B returns no results from that mailbox and the response includes a message such as:

> Could not search in mailbox colleague@example.com — Microsoft does not offer an API to search in shared folders from this mailbox.

**Cause:** Microsoft Graph requires full mailbox access for `$search` queries. When a user shares only individual folders, Microsoft Graph returns HTTP 403 to any search request against that mailbox — regardless of whether a specific folder is targeted or not. There is no Microsoft Graph API that supports keyword search scoped to a partially-delegated mailbox.

**Workaround options:**

- **Get Full Access.** Ask your colleague (or an Exchange administrator) to grant you Full Access (Read & Manage) to their mailbox. This allows `$search` queries against the entire mailbox, including the previously shared folders.
- **Use a shared mailbox.** Convert the colleague's mailbox to a Microsoft 365 shared mailbox, connect it to the MCP as its own account, and grant Full Access to everyone who needs to search it. See [Setup — Shared inbox configured as a normal inbox](#3-shared-inbox-configured-as-a-normal-inbox).
