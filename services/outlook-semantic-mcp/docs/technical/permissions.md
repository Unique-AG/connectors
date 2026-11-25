<!-- confluence-page-id: 2064252966 -->
<!-- confluence-space-key: PUBDOC -->

All permissions are **Delegated** (not Application), meaning they act on behalf of the signed-in user and can only access data that user has access to.

## Permission Summary

The server does not request a fixed list. It computes the list from `MCP_TOOLS`, `DELEGATED_ACCESS_SCAN` and `MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS`, and uses it for the OAuth authorize request, token refresh and the Graph client. See [Configuration — Requested Graph permissions](../operator/configuration.md#Requested-Graph-permissions) for the rule and example results.

| Permission | Type | Admin Consent | Requested when | Purpose |
|------------|------|---------------|----------------|---------|
| `User.Read` | Delegated | No | Always | Resolve user identity and profile at sign-in, and translate message ids (`translateExchangeIds`) |
| `Mail.Read` | Delegated | No | Always, unless `Mail.ReadWrite` is requested | Read emails for sync, search and `open_email` in the user's own mailbox |
| `Mail.ReadWrite` | Delegated | No | A draft tool is listed in `MCP_TOOLS` | Read emails like `Mail.Read`; create and edit draft emails in the user's mailbox |
| `Mail.Read.Shared` | Delegated | No | `DELEGATED_ACCESS_SCAN` is not `disabled`, unless `Mail.ReadWrite.Shared` is requested | Read emails in mailboxes the user has been granted delegated access to |
| `Mail.ReadWrite.Shared` | Delegated | No | `DELEGATED_ACCESS_SCAN` is not `disabled` and a draft tool is listed in `MCP_TOOLS` | Read emails like `Mail.Read.Shared`; create and edit drafts in those mailboxes |
| `User.Read.All` | Delegated | Yes | `DELEGATED_ACCESS_SCAN` is not `disabled` | Resolve the addresses in `DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS` through Graph `/users` |
| `MailboxSettings.Read` | Delegated | No | `list_categories`, `search_emails`, `fetch_next_search_pages`, `open_email` or a calendar tool other than `list_calendars` and `respond_to_invite` is listed | Read mailbox settings and folder structure |
| `People.Read` | Delegated | No | `lookup_contacts` is listed | Look up contacts and people for address resolution |
| `Calendars.ReadWrite.Shared` | Delegated | No | A calendar tool is listed in `MCP_TOOLS` | List calendars and read/write events, including calendars shared with the user |
| `offline_access` | Delegated | No | Always | Obtain refresh tokens for background sync |

`MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS` can add any of these Graph permissions on top, for an Entra app granted more than the selection needs. A write permission replaces its read permission: `Mail.ReadWrite` removes `Mail.Read`, and `Mail.ReadWrite.Shared` removes `Mail.Read.Shared`.

**Only `User.Read.All` requires admin consent**, and the server requests it only with shared mailboxes on or when `MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS` lists it. Every other permission, calendar included, is user-consentable — see [`Calendars.ReadWrite.Shared`](https://learn.microsoft.com/en-us/graph/permissions-reference#calendarsreadwriteshared). With `DELEGATED_ACCESS_SCAN=disabled` and no `User.Read.All` in `MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS`, users can connect their own accounts without IT intervention, unless the tenant disables user consent.

Admin involvement is still needed in two cases: the tenant has disabled user consent for applications (a tenant-wide policy, not a property of these scopes), or the admin wants to pre-grant consent organisation-wide so users never see the consent screen. Asking for fewer permissions than the app was granted needs no consent; asking for one it was not granted does. Independently of consent, `Calendars.ReadWrite.Shared` must be **registered** on the Entra app (Terraform `calendar_integration = "enabled"`) before a calendar tool is listed in `MCP_TOOLS`, otherwise token refresh requests a scope the app does not expose.

## Understanding Consent Requirements

**All permissions are standard Microsoft delegated consent, not Outlook Semantic MCP specific.** Users can connect independently for both mail and calendar. Admins can optionally pre-grant consent organisation-wide, and must grant it if the tenant disables user consent for applications.

For the full consent flow explanation including admin consent and multi-tenant setup, see [Authentication — Understanding Consent Flows](../operator/authentication.md#Understanding-Consent-Flows).

## Least-Privilege Justification

Each permission is the minimum required for its function. No narrower alternative exists.

### `User.Read`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Retrieve the signed-in user's profile (ID, email, display name) |
| **Used For** | Identifying the user when storing tokens and creating Graph subscriptions |
| **Why Not Less** | This is the minimum permission to read any user data |
| **Why Not `User.ReadBasic.All`** | That permission reads other users; we only need the signed-in user |

### `Mail.Read`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read email messages in the user's mailbox |
| **Used For** | Fetching email bodies, headers, and metadata during full sync and live catch-up; search and `open_email` |
| **Why Not `Mail.ReadBasic`** | Sync, search and `open_email` need message bodies, which `Mail.ReadBasic` does not cover |
| **Note** | Always requested, unless `Mail.ReadWrite` is requested, which includes it |

### `Mail.ReadWrite`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read and create email messages in the user's mailbox |
| **Used For** | Everything `Mail.Read` covers; creating draft emails via the `draft_email` tool (POST `/me/messages`); editing drafts via `update_draft_email` (PATCH `/me/messages/{id}`) and adding their attachments (POST `/me/messages/{id}/attachments`) and removing them (DELETE `/me/messages/{id}/attachments/{attachmentId}`) |
| **Why Not `Mail.Read` + `Mail.ReadWrite`** | `Mail.ReadWrite` already includes full read access, so `Mail.Read` is dropped when `Mail.ReadWrite` is requested |
| **Why Not `Mail.Send`** | The server only creates drafts — sending is a deliberate user action in Outlook. `Mail.Send` is not requested. |
| **Note** | Requested when a draft tool (`draft_email`, `update_draft_email`, `add_attachments_to_draft_email`, `remove_attachments_from_draft_email`) is listed in `MCP_TOOLS` |

### `Mail.Read.Shared`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read delegated mailboxes the user has been granted access to via Exchange admin |
| **Used For** | Delegated mailbox discovery and search via `/users/{ownerEmail}/messages` and `/users/{ownerEmail}/mailFolders`, and `open_email` on those mailboxes |
| **Why Not Less** | No narrower delegated-shared permission exists for reading a delegated mailbox |
| **Note** | Requested when `DELEGATED_ACCESS_SCAN` is not `disabled`, unless `Mail.ReadWrite.Shared` is requested, which includes it |

### `Mail.ReadWrite.Shared`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read delegated mailboxes and create drafts in them |
| **Used For** | Everything `Mail.Read.Shared` covers; creating and editing drafts in a shared or delegated mailbox through the `mailbox` parameter of the draft tools |
| **Why Not Less** | No narrower delegated-shared permission exists for read and draft access on a delegated mailbox |
| **Note** | Requested when `DELEGATED_ACCESS_SCAN` is not `disabled` and a draft tool is listed in `MCP_TOOLS`. With `DELEGATED_ACCESS_SCAN=disabled` it is not requested, and the tools with a `mailbox` parameter refuse any mailbox other than the user's own |

### `User.Read.All`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read other users' profiles in the tenant |
| **Used For** | Resolving the addresses in `DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS` through Graph `/users` during shared-mailbox sync |
| **Note** | Requested when `DELEGATED_ACCESS_SCAN` is not `disabled` |

### `MailboxSettings.Read`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read the mailbox time zone and the category list |
| **Used For** | `list_categories` (`/me/outlook/masterCategories`), and the mailbox time zone (`/me/mailboxSettings`) that `search_emails`, `fetch_next_search_pages`, `open_email` and the calendar tools use to show dates |
| **Why Not Less** | It is the least privileged permission for both endpoints |
| **Why Not `MailboxSettings.ReadWrite`** | The server never modifies mailbox settings |
| **Note** | Requested when one of those tools is listed in `MCP_TOOLS` |

### `People.Read`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read the user's relevant people list (contacts, colleagues, frequent contacts) |
| **Used For** | The `lookup_contacts` tool — searching for email addresses and display names for draft recipients |
| **Why Not Less** | This is the minimum permission for the People API |
| **Why Not `Contacts.Read`** | `People.Read` provides the Microsoft People API which returns a richer relevance-ranked result set. `Contacts.Read` only covers the Contacts folder, not the full people graph. |
| **Note** | Requested when `lookup_contacts` is listed in `MCP_TOOLS` |

### `Calendars.ReadWrite.Shared`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read and write the signed-in user's calendars, including calendars shared with them |
| **Used For** | Calendar tools (`list_calendars`, `search_calendar_events`, `check_availability`, `suggest_meeting_times`, `respond_to_invite`, `create_event`, `update_event`, `cancel_event`). Live Graph query-through; no calendar ingest |
| **Why Not `Calendars.Read`** | Writes (create/update/respond/cancel) need write. `Calendars.ReadWrite` does not cover calendars shared with the user |
| **Note** | Requested at OAuth time only when a calendar tool is listed in `MCP_TOOLS`. The Entra app registers the scope only when Terraform `calendar_integration = "enabled"`. It is not on the mail-only consent screen |

### `offline_access`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Obtain refresh tokens for long-lived sessions |
| **Used For** | Refreshing expired Microsoft access tokens without user re-authentication |
| **Why Required** | Without this, users would need to re-authenticate every ~1 hour when access tokens expire (Microsoft limit, not configurable), interrupting background email sync |

## Why Delegated (Not Application) Permissions

| Factor | Delegated (used) | Application (not used) |
|--------|-------------------|------------------------|
| User involvement | User signs in and consents | No user; admin pre-configures |
| Data access scope | Only the signed-in user's data | All users' data in tenant |
| Setup requirement | None (self-service) | Admin creates Application Access Policies via PowerShell |
| Least privilege | Yes — user controls their own data | No — broad tenant access |

The MCP model requires **self-service user connections** where each user:

1. Connects their own account
2. Controls what data they share
3. Can permanently delete their synced inbox data at any time via `delete_inbox_data`

Application permissions would require tenant administrators to create Application Access Policies for each user via PowerShell — impractical for self-service MCP connections. See [Microsoft Entra ID - Authentication flows](https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows) for details.

## OIDC Scopes

In addition to the Graph permissions above, the OAuth flow also requests the standard OIDC scopes `openid`, `profile`, and `email`. These are not Microsoft Graph permissions — they are used to obtain the user's identity (ID token) during sign-in and are not subject to admin consent.

## Permission Reference Links

- [Microsoft Graph Permissions Reference](https://learn.microsoft.com/en-us/graph/permissions-reference) - Official permission documentation
- [Mail.ReadWrite](https://graphpermissions.merill.net/permission/Mail.ReadWrite) - Third-party permission explorer
- [People.Read](https://graphpermissions.merill.net/permission/People.Read) - Third-party permission explorer

## Related Documentation

- [Authentication](../operator/authentication.md) - Entra ID app registration and consent flows
- [Architecture](./architecture.md) - Token isolation and authentication layers
- [Security](./security.md) - Encryption, PKCE, and threat model
- [Tools — Calendar](./tools.md#Calendar) - Calendar tools that use `Calendars.ReadWrite.Shared`
- [Configuration — Calendar tools](../operator/configuration.md#Calendar-tools) - Operator enablement order
