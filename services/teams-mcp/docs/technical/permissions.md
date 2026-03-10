<!-- confluence-page-id: 1802240023 -->
<!-- confluence-space-key: PUBDOC -->

All permissions are **Delegated** (not Application), meaning they act on behalf of the signed-in user and can only access data that user has access to.

## Permission Summary

| Permission | Type | ID | Admin Consent | Required |
|------------|------|-----|---------------|----------|
| `User.Read` | Delegated | `e1fe6dd8-ba31-4d61-89e7-88639da4683d` | No | Yes |
| `Calendars.Read` | Delegated | `465a38f9-76ea-45b9-9f34-9e8b0d4b0b42` | No | Yes |
| `OnlineMeetings.Read` | Delegated | `9be106e1-f4e3-4df5-bdff-e4bc531cbe43` | No | Yes |
| `OnlineMeetingRecording.Read.All` | Delegated | `190c2bb6-1fdd-4fec-9aa2-7d571b5e1fe3` | Yes | Yes |
| `OnlineMeetingTranscript.Read.All` | Delegated | `30b87d18-ebb1-45db-97f8-82ccb1f0190c` | Yes | Yes |
| `offline_access` | Delegated | `7427e0e9-2fba-42fe-b0c0-848c9e6a8182` | No | Yes |
| `ChannelMessage.Send` | Delegated | `ebf0f66e-9fb1-49e4-a278-222f76911cf4` | No | Yes |
| `ChatMessage.Send` | Delegated | `116b7235-2ffd-4103-963e-baec9c8e5c8b` | No | Yes |
| `Chat.ReadBasic` | Delegated | `9547fcb5-d03f-419d-9948-5928bbf71b0f` | No | Yes |
| `Chat.Read` | Delegated | `f501c180-9344-439a-bca0-6cbf209fd270` | No | Yes |
| `Team.ReadBasic.All` | Delegated | `2280dda6-0bfd-44ee-a2f4-cb867cfc4c1e` | No | Yes |
| `Channel.ReadBasic.All` | Delegated | `3aeca27b-ee3a-4c2b-8ded-80376e2134a4` | No | Yes |

## Understanding Consent Requirements

**This is standard Microsoft behavior, not Teams MCP specific.** All Microsoft 365 apps use the same consent model.

### Standard Microsoft Consent Process

1. **Admin adds the app and grants admin-required permissions**

   - Organization-wide OR per-user
   - For Teams MCP: `OnlineMeetingRecording.Read.All` and `OnlineMeetingTranscript.Read.All` require admin consent
   - The 6 chat messaging permissions (`ChannelMessage.Send`, `ChatMessage.Send`, `Chat.ReadBasic`, `Chat.Read`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`) do **not** require admin consent and can be approved by individual users.

2. **Admin approval workflow (if tenant has it enabled)**

   - Users request admin approval
   - Admin approves app for that user
   - This is in addition to Step 1

3. **User consent (always required for delegated permissions)**

   - Each user must consent individually
   - Required even after admin consent (Microsoft's requirement for delegated permissions)

**Microsoft Documentation:**

- [User and admin consent overview](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview) - Standard Microsoft consent flows
- [Grant admin consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent) - Step-by-step guide
- [Admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) - Per-user approval process

## Least-Privilege Justification

Each permission is the minimum required for its function. No narrower alternatives exist.

### `User.Read`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Retrieve the signed-in user's profile (ID, email, display name) |
| **Used For** | Identifying the user when storing tokens and creating subscriptions |
| **Why Not Less** | This is the minimum permission to read any user data |
| **Why Not `User.ReadBasic.All`** | That permission reads other users; we only need the signed-in user |

### `Calendars.Read`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read the user's calendar events |
| **Used For** | Determining if a meeting is recurring by querying the calendar event associated with an online meeting |
| **Why Not Less** | No narrower permission exists for reading calendar events |
| **Why Not `Calendars.ReadWrite`** | We don't create or modify calendar events, only read them |

### `OnlineMeetings.Read`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read meeting metadata (subject, start/end time, participants) |
| **Used For** | Fetching meeting details when a transcript notification arrives |
| **Why Not Less** | No narrower permission exists for reading meeting data |
| **Why Not `OnlineMeetings.ReadWrite`** | We don't create or modify meetings, only read them |

### `OnlineMeetingRecording.Read.All`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read recordings from all meetings the user can access |
| **Used For** | Downloading MP4 recording files to store alongside transcripts |
| **Why Not Less** | No per-meeting recording permission exists; `.All` is the minimum |
| **Why Not Application Permission** | Would require tenant admin to create Application Access Policies per-user; impractical for self-service MCP connections |
| **Admin Consent** | Required because recordings contain audio/video of meetings |

### `OnlineMeetingTranscript.Read.All`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read transcripts from all meetings the user can access |
| **Used For** | Downloading VTT transcript content for ingestion |
| **Why Not Less** | No per-meeting transcript permission exists; `.All` is the minimum |
| **Why Not Application Permission** | Would require tenant admin to create Application Access Policies per-user; impractical for self-service MCP connections |
| **Admin Consent** | Required because transcripts may contain sensitive meeting content |

### `offline_access`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Obtain refresh tokens for long-lived sessions |
| **Used For** | Refreshing expired access tokens without user re-authentication |
| **Why Required** | Without this, users would need to re-authenticate every ~1 hour when access tokens expire |

### `ChannelMessage.Send`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Send messages to Microsoft Teams channels |
| **Used For** | `send_channel_message` tool to post messages on behalf of the user |
| **Why Not Less** | No narrower permission exists for sending channel messages |
| **Why Not `ChannelMessage.ReadWrite`** | We only send messages, not read or modify them |

### `ChatMessage.Send`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Send messages to Microsoft Teams chats |
| **Used For** | `send_chat_message` tool to post messages on behalf of the user |
| **Why Not Less** | No narrower permission exists for sending chat messages |
| **Why Not `Chat.ReadWrite`** | We only send messages, not read full chat content via this permission |

### `Chat.ReadBasic`

| Aspect | Detail |
|--------|--------|
| **Purpose** | List the user's chats with basic metadata (topic, members, chat type) |
| **Used For** | `list_chats` tool and resolving chats by topic or member name |
| **Why Not Less** | No narrower permission exists for listing chats |
| **Why Not `Chat.Read`** | `Chat.ReadBasic` is sufficient for listing chats; `Chat.Read` is only needed for reading message content |

### `Chat.Read`

| Aspect | Detail |
|--------|--------|
| **Purpose** | Read full message content from Teams chats |
| **Used For** | `get_chat_messages` tool to retrieve message history |
| **Why Not Less** | `Chat.ReadBasic` does not grant access to message content |
| **Why Not `Chat.ReadWrite`** | We do not modify or delete chat messages |

### `Team.ReadBasic.All`

| Aspect | Detail |
|--------|--------|
| **Purpose** | List all Teams the user is a member of |
| **Used For** | `list_teams` tool and resolving teams by display name |
| **Why Not Less** | No narrower permission exists for listing joined teams |
| **Why Not `Team.Read.All`** | `Team.ReadBasic.All` is sufficient for listing teams with display names |

### `Channel.ReadBasic.All`

| Aspect | Detail |
|--------|--------|
| **Purpose** | List channels in a Team |
| **Used For** | `list_channels` tool and resolving channels by display name |
| **Why Not Less** | No narrower permission exists for listing channels |
| **Why Not `Channel.Read.All`** | `Channel.ReadBasic.All` is sufficient for listing channels with display names |

## Why Delegated (Not Application) Permissions

<div style="max-width: 800px;">

```mermaid
%%{init: {'theme': 'neutral', 'themeVariables': { 'fontSize': '14px' }}}%%
flowchart LR
    subgraph Delegated["Delegated Permissions (Used)"]
        U1["User signs in"]
        U2["Consents to permissions"]
        U3["Token accesses user's data only"]
    end

    subgraph Application["Application Permissions (Not Used)"]
        A1["No user sign-in"]
        A2["Admin configures policies"]
        A3["Token accesses all tenant data"]
    end

    U1 --> U2 --> U3
    A1 --> A2 --> A3

    style Delegated fill:#e8f5e9
    style Application fill:#ffebee
```

</div>

| Factor | Delegated | Application |
|--------|-----------|-------------|
| User involvement | User signs in and consents | No user; admin pre-configures |
| Data access scope | Only the signed-in user's data | All users' data in tenant |
| Setup requirement | None (self-service) | Admin creates Access Policies |
| Least privilege | Yes - user controls their own data | No - broad tenant access |

The MCP model requires **self-service user connections** where each user:

1. Connects their own account
2. Controls what data they share
3. Can disconnect at any time

Application permissions would require tenant administrators to pre-configure access for each user, defeating the self-service model.

## Permission Reference Links

- [Microsoft Graph Permissions Reference](https://learn.microsoft.com/en-us/graph/permissions-reference) - Official Microsoft documentation
- [Calendars.Read](https://graphpermissions.merill.net/permission/Calendars.Read) - Third-party permission explorer
- [OnlineMeetingRecording.Read.All](https://graphpermissions.merill.net/permission/OnlineMeetingRecording.Read.All) - Third-party permission explorer
- [OnlineMeetingTranscript.Read.All](https://graphpermissions.merill.net/permission/OnlineMeetingTranscript.Read.All) - Third-party permission explorer
- [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/overview) - Graph API overview

## Related Documentation

- [Architecture](./architecture.md) - System components and infrastructure
- [Security](./security.md) - Encryption, PKCE, and threat model
- [Flows](./flows.md) - User connection, subscription lifecycle, transcript processing
