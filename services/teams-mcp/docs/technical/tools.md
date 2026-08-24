<!-- confluence-page-id: 2398519349 -->
<!-- confluence-space-key: PUBDOC -->

The Teams MCP Server exposes **8 chat & messaging tools**, which interact with Microsoft Teams chats and channels synchronously through the Microsoft Graph API: list teams/channels/chats, read messages, search across messages, and send messages.

!!! note "Chat tools can be turned off"
    The eight chat & messaging tools are registered by default (`CHAT_INTEGRATION=enabled`). Setting `CHAT_INTEGRATION=disabled` — used for an **ingestion-only** deployment — leaves none of them registered, and the messaging Graph scopes are not requested. The four transcript tools below are governed separately by `UNIQUE_INTEGRATION`.

Four further tools exist only in deployments with meeting-transcript capture enabled — see [Transcript & Knowledge-Base Management](#Transcript-&-Knowledge-Base-Management) below.

Chat and messaging tools target chats and channels by id: you discover the id with a `list_*` tool (or `search_messages`), then pass it to the tool that reads or writes:

```
list_teams / list_chats / list_channels  →  id  →  get_*_messages / send_*_message
```

The `list_*` tools return distinguishing metadata (creation dates, last-message timestamps, archived/membership flags, member names) so the agent can pick the right id when several teams, chats, or channels share a display name.

## Tool Overview

| Tool | Category | Mutating | Description |
|------|----------|----------|-------------|
| [`list_teams`](#list_teams) | Teams & Channels | No | List the Teams the signed-in user belongs to |
| [`list_channels`](#list_channels) | Teams & Channels | No | List the channels in a team |
| [`list_chats`](#list_chats) | Chats | No | List the signed-in user's chats |
| [`get_chat_messages`](#get_chat_messages) | Messages | No | Read recent messages from a chat |
| [`get_channel_messages`](#get_channel_messages) | Messages | No | Read recent messages from a channel |
| [`send_chat_message`](#send_chat_message) | Messages | Yes | Send a plain-text message to a chat |
| [`send_channel_message`](#send_channel_message) | Messages | Yes | Send a plain-text message to a channel |
| [`search_messages`](#search_messages) | Search | No | Search messages across chats and channels |

**Mutating** means the tool posts a new message to a chat or channel via Microsoft Graph, on behalf of the signed-in user.

| Tool | What it mutates |
|------|----------------|
| `send_chat_message` | Posts a new plain-text message to the target chat via Microsoft Graph as the signed-in user |
| `send_channel_message` | Posts a new plain-text message to the target channel via Microsoft Graph as the signed-in user |

!!! warning "Chat and channel messages are not ingested"
    The message tools read and write Teams messages live through Microsoft Graph. **Chat and channel messages are never copied into the Unique knowledge base** — `get_*_messages` and `search_messages` query Microsoft Graph on every call.

---

## Teams & Channels

### `list_teams`

List all Microsoft Teams the signed-in user is a member of. Each team carries an `isArchived` flag (archived teams are read-only) to distinguish teams that share a display name.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `includeDescriptions` | boolean | No | `false` | Include each team's description. Useful when several teams have similar names. |

**Returns:** A `teams` array. Each entry has `teamId`, `displayName`, `isArchived` (`true`/`false`/`null`), and `description` (only when `includeDescriptions` is `true` and a description exists). Pass `teamId` to `list_channels`, `get_channel_messages`, or `send_channel_message`.

**Example:**

```json
{
  "teams": [
    { "teamId": "19:abc...@thread.tacv2", "displayName": "Engineering", "isArchived": false },
    { "teamId": "19:def...@thread.tacv2", "displayName": "Engineering", "isArchived": true }
  ]
}
```

---

### `list_channels`

List all channels in a team, identified by `teamId`. Each channel carries its creation date and membership type (`standard`, `private`, or `shared`) to tell apart channels that share a display name.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `teamId` | string | Yes | — | Exact team id from `list_teams`. |
| `includeDescriptions` | boolean | No | `false` | Include each channel's description. |

**Returns:** The `teamId` and a `channels` array. Each entry has `channelId`, `displayName`, `createdDateTime`, `membershipType`, and `description` (only when `includeDescriptions` is `true`). Pass `teamId` + `channelId` to `get_channel_messages` or `send_channel_message`.

**Example:**

```json
{
  "teamId": "19:abc...@thread.tacv2",
  "channels": [
    {
      "channelId": "19:ch1...@thread.tacv2",
      "displayName": "General",
      "createdDateTime": "2023-04-01T09:00:00Z",
      "membershipType": "standard"
    }
  ]
}
```

---

## Chats

### `list_chats`

List the signed-in user's chats (1:1, group, and meeting chats), most recent first. Each chat carries its creation date and last-message timestamp to tell apart chats that share a topic or members. For chats without a topic (typically 1:1 chats), the member list is returned so the chat can be identified by participant.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer (1–50) | No | `50` | Maximum number of chats to return. |
| `includeMemberEmails` | boolean | No | `false` | Include member email addresses (only for topic-less chats). Useful when two members share a display name. |

**Returns:** A `chats` array and a `truncated` flag (`true` when more chats exist than were returned). Each chat has `chatId`, `chatType`, `topic` (nullable), `createdDateTime`, `lastMessageAt`, and — for chats without a topic — a `members` array (`displayName`, plus `email` when `includeMemberEmails` is `true`). Pass `chatId` to `get_chat_messages` or `send_chat_message`.

**Example:**

```json
{
  "chats": [
    {
      "chatId": "19:meeting_xyz@thread.v2",
      "chatType": "meeting",
      "topic": "Weekly Sync",
      "createdDateTime": "2024-01-10T08:00:00Z",
      "lastMessageAt": "2024-06-20T14:32:00Z"
    },
    {
      "chatId": "19:1on1@unq.gbl.spaces",
      "chatType": "oneOnOne",
      "topic": null,
      "createdDateTime": "2023-11-02T10:00:00Z",
      "lastMessageAt": "2024-06-19T09:15:00Z",
      "members": [{ "displayName": "Alice Smith" }]
    }
  ],
  "truncated": false
}
```

---

## Messages

The two `get_*_messages` tools share the same content-shaping options. Content can be returned **normalized** (the default — Teams HTML converted to readable plain text) or **raw** (Teams HTML verbatim). Normalization rewrites `<at>Name</at>` mentions to `@Name`, attachment references to `[attachment: name]` (or `[attachment]` when the name is unknown), adaptive-card payloads to `[card]`, and blank/tombstone messages to `[deleted]`.

### `get_chat_messages`

Retrieve recent messages from a chat, identified by `chatId`. Call `list_chats` (or `search_messages`) first to find the `chatId`.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `chatId` | string | Yes | — | Exact chat id from `list_chats` or `search_messages`. |
| `limit` | integer (1–50) | No | `20` | Maximum number of messages to return (newest first). |
| `includeSystemMessages` | boolean | No | `false` | Include event notifications (member added, call ended). |

**Returns:** The `chatId` and a `messages` array (newest first). Each message has `id`, `senderDisplayName` (nullable), `content` and `createdDateTime`. Bodies are always normalized plain text, never Teams HTML, and `createdDateTime` is the ISO 8601 value Graph returns.

**Example:**

```json
{
  "chatId": "19:1on1@unq.gbl.spaces",
  "messages": [
    {
      "id": "1718901120000",
      "senderDisplayName": "Alice Smith",
      "content": "@Bob Jones can you review the PR? [attachment: design.pdf]",
      "createdDateTime": "2024-06-20T14:32:07.113Z"
    }
  ]
}
```

---

### `get_channel_messages`

Retrieve recent messages from a channel, identified by `teamId` + `channelId`. Call `list_teams` then `list_channels` first to find the ids.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `teamId` | string | Yes | — | Exact team id from `list_teams`. |
| `channelId` | string | Yes | — | Exact channel id from `list_channels` (for that team). |
| `limit` | integer (1–50) | No | `20` | Maximum number of messages to return (newest first). |
| `includeSystemMessages` | boolean | No | `false` | Include event notifications (member added, call ended). |

**Returns:** The `teamId`, `channelId`, and a `messages` array (same shape as `get_chat_messages`).

**Example:**

```json
{
  "teamId": "19:abc...@thread.tacv2",
  "channelId": "19:ch1...@thread.tacv2",
  "messages": [
    {
      "id": "1718900000000",
      "senderDisplayName": "Carol Lee",
      "content": "Deploy is green.",
      "createdDateTime": "2024-06-20 13:50"
    }
  ]
}
```

---

### `send_chat_message`

Send a plain-text message to a chat (1:1 or group), identified by `chatId`. Call `list_chats` first to find the `chatId`.

!!! warning "Plain text only"
    Send tools accept **plain text only**. Rich content, `@mentions`, threading/replies, and attachment uploads are not supported. The message is posted as the signed-in user.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `chatId` | string | Yes | — | Exact chat id from `list_chats` or `search_messages`. |
| `message` | string | Yes | — | Plain-text message content to send. |

**Returns:** `messageId` and the `chatId` the message was posted to.

**Example:**

```json
{ "messageId": "1718901500000", "chatId": "19:1on1@unq.gbl.spaces" }
```

---

### `send_channel_message`

Send a plain-text message to a channel, identified by `teamId` + `channelId`. Call `list_teams` then `list_channels` first to find the ids.

!!! warning "Plain text only"
    Plain text only — no rich content, `@mentions`, threading/replies, or attachments. The message is posted as the signed-in user.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `teamId` | string | Yes | — | Exact team id from `list_teams`. |
| `channelId` | string | Yes | — | Exact channel id from `list_channels` (for that team). |
| `message` | string | Yes | — | Plain-text message content to send. |
| `includeWebUrl` | boolean | No | `false` | Include the Teams web URL of the sent message in the response. |

**Returns:** `messageId`, and `webUrl` when `includeWebUrl` is `true` and Graph returned one.

**Example:**

```json
{ "messageId": "1718901600000", "webUrl": "https://teams.microsoft.com/l/message/..." }
```

---

## Search

### `search_messages`

Search Microsoft Teams messages by keyword across 1:1 chats, group chats, and channels in a single query, using the [Microsoft Search API](https://learn.microsoft.com/en-us/graph/search-concept-overview) (`POST /search/query` on Graph **v1.0**). Supports filters on sender, recipient, mentions, date range, attachments, and read/mention state. Every addressable hit is fetched to fill in its message body, so a follow-up `get_chat_messages` or `get_channel_messages` call is normally unnecessary. At least one search criterion (`query`, `from`, `to`, `mentions`, `sentAfter`, `sentBefore`, `hasAttachment`, `isRead`, or `isMentioned`) must be provided.

There is no way to scope a Graph search to chats or to channels, and the search projection carries no container type — so every hit is returned and each row reports the container it can prove. A hit is `channel` only when it carries **both** `channelIdentity.teamId` and `channelIdentity.channelId`, `chat` when it carries a `chatId`, and `unknown` otherwise. Filter client-side on that field if you only want one kind.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | No | — | Free-text keywords to match in message content. Multi-word terms are quoted automatically. |
| `from` | string | No | — | Sender name or email (KQL `from:`). Matches the message author. |
| `to` | string | No | — | Recipient name or email (KQL `to:`). |
| `mentions` | string (GUID) | No | — | User object id of a mentioned user; dashes are stripped automatically. |
| `sentAfter` | string (ISO date) | No | — | Only messages sent on or after this date (e.g. `2024-01-15`). |
| `sentBefore` | string (ISO date) | No | — | Only messages sent on or before this date (e.g. `2024-01-31`). |
| `hasAttachment` | boolean | No | — | Restrict to messages with (`true`) or without (`false`) attachments. |
| `isRead` | boolean | No | — | Restrict to read (`true`) or unread (`false`) messages. |
| `isMentioned` | boolean | No | — | Restrict to messages where the signed-in user is (`true`) or is not (`false`) mentioned. |
| `offset` | integer (≥ 0) | No | `0` | Number of results to skip for pagination (maps to Graph `from`). |
| `size` | integer (1–25) | No | `25` | Maximum number of results per page. Not a Graph limit — Microsoft caps a page at 25 for the `message` and `event` entities only, never for `chatMessage`. Every hit costs one extra Graph call, so the page size is also the size of that fan-out. |

**Returns:** A `messages` array, `returnedCount` (rows on **this page**, not total corpus matches — Graph reports `total` per page for Teams messages), and `moreResultsAvailable`. Paginate by advancing `offset` by `returnedCount`, and stop when `moreResultsAvailable` is `false` or `returnedCount` is `0`. Each hit has:

| Field | Description |
|-------|-------------|
| `id` | Message id |
| `source` | `chat`, `channel`, or `unknown`. `channel` requires **both** `teamId` and `channelId` on the hit; `chat` requires a `chatId`; anything else is `unknown` and cannot be fetched |
| `chatId` | Chat id (populated only for a `chat` hit, else `null`) |
| `teamId` | Team id (populated only for a `channel` hit, else `null`) |
| `channelId` | Channel id (populated only for a `channel` hit, else `null`) |
| `senderDisplayName` | Sender name (nullable). Read from the hit's mailbox identity, which is what the search projection carries, then filled from the hydrated message when the hit named nobody, and as a last resort from the sender's bare email address — so this field can hold an address rather than a name |
| `summary` | Search snippet, with Graph's hit-highlighting markup stripped (nullable) |
| `content` | Hydrated message body, always normalized to readable plain text — a message with no text of its own reads as a placeholder (`[image]`, `[card]`, `[attachment: name]`), and a deleted message reads as `[deleted]` rather than being absent. Absent for an `unknown` hit, for a reply inside a channel thread, or when the fetch failed (forbidden, throttled, or otherwise). The row carries no reason code, so an absent `content` does not say which |
| `createdDateTime` | Message timestamp (nullable) |
| `webUrl` | Link to the message (nullable). Graph's retrievable-property list names a Teams deep link (`webUrl`), but the search projection often carries an Outlook Web link (`webLink`) instead, and either may be returned here — do not label it "open in Teams" |

Pass the returned `chatId` (or `teamId` + `channelId`) straight to `get_*_messages` or `send_*_message`.

!!! note "How hydration behaves"
    The search projection of a `chatMessage` carries no body, and Graph offers no way to ask for one, so every hit is fetched individually: one extra Graph call per hit (an N+1 fan-out), capped at 3 concurrent requests. A hit is fetched by the ids it actually carries — a message id plus either both channel ids or a chat id — so an `unknown` hit costs no call at all. If an individual fetch fails, that row falls back to summary-only (no `content`) rather than failing the whole page, and the failure is logged at `warn`. Two consequences: a tenant without admin consent for `ChannelMessage.Read.All` gets bodyless channel rows, and a hit that is a **reply inside a channel thread** always gets a bodyless row — Graph addresses a reply under its parent post (`.../messages/{rootId}/replies/{id}`) and the search index does not name the parent, so the reply's own id cannot be fetched. Graph also throttles reads of a single chat or channel hard, so a page whose hits all come from one busy channel may lose bodies to throttling. Hydration as a whole is bounded at 15 seconds: past that budget the remaining hits come back without `content` rather than holding the response open, because the Graph client retries a `429` while honouring `Retry-After` and that can run into minutes.

**Example:**

```json
{
  "messages": [
    {
      "id": "1718900000000",
      "source": "channel",
      "chatId": null,
      "teamId": "fbe2bf47-16c8-47cf-b4a5-4b9b187c508b",
      "channelId": "19:ch1...@thread.tacv2",
      "senderDisplayName": "Carol Lee",
      "summary": "...Deploy is green",
      "content": "Deploy is green. Rollout finished at 13:49.",
      "createdDateTime": "2024-06-20T13:50:00Z",
      "webUrl": "https://teams.microsoft.com/l/message/..."
    }
  ],
  "returnedCount": 1,
  "moreResultsAvailable": false
}
```

---

## Transcript & Knowledge-Base Management

When `UNIQUE_INTEGRATION=enabled`, four additional tools manage meeting-transcript capture into the Unique knowledge base: `ingest_meeting`, `verify_kb_integration_status`, `start_kb_integration`, and `stop_kb_integration`. They are not registered in a chat-only deployment.

Their full reference — parameters, return values, and the subscription behaviour behind them — is in [Recordings & Transcripts — Ingestion tools](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2399993877/Recordings+Transcripts+-+Technical+Manual#Ingestion-tools).

---

## Related Documentation

- [Architecture](./architecture.md) - System components, including the chat module
- [Flows](./flows.md) - Sequence diagrams for the read, search, and send flows
- [Permissions](./permissions.md) - Microsoft Graph permissions required by these tools
- [Security](./security.md) - Token isolation, delegated access, and the message-send write surface
- [Recordings & Transcripts - Technical Manual](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2399993877/Recordings+Transcripts+-+Technical+Manual) - The transcript and knowledge-base tools, and the capture pipeline behind them
