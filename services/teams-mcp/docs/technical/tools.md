<!-- confluence-page-id: 2398519349 -->
<!-- confluence-space-key: PUBDOC -->

# Teams MCP - Tools

The Teams MCP Server exposes **14 tools** in two categories:

- **Chat & messaging tools** (8) interact with Microsoft Teams chats and channels synchronously through the Microsoft Graph API: list teams/channels/chats, read messages, search across messages, and send messages.
- **Transcript & knowledge-base tools** (6) manage meeting-transcript ingestion into the Unique knowledge base and search the transcripts that have already been ingested.

All chat and messaging tools use **id-only targeting**. There is no name-based addressing: you discover the id you need with a `list_*` tool (or `search_messages`), then pass that id to the tool that reads or writes. The canonical workflow is:

```
list_teams / list_chats / list_channels  →  id  →  get_*_messages / send_*_message
```

The `list_*` tools return distinguishing metadata (creation dates, last-message timestamps, archived/membership flags, member names) so the agent can pick the right id when several teams, chats, or channels share a display name.

!!! note "Historical note: id-only targeting"
    Earlier pre-release builds accepted display names and resolved them with an interactive disambiguation picker. That path was removed: every chat/channel tool now takes ids only, and the `list_*` tools surface the metadata needed to choose between same-named entities. (The transcript `ingest_meeting` tool still uses interactive elicitation to pick between multiple transcripts of one recurring meeting — see below.)

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
| [`find_transcripts`](#find_transcripts) | Transcript & KB | No | Semantic + keyword search within ingested transcripts |
| [`list_meetings`](#list_meetings) | Transcript & KB | No | Browse ingested meetings by date/organizer/participant |
| [`ingest_meeting`](#ingest_meeting) | Transcript & KB | Yes | Ingest a specific meeting's transcript on demand |
| [`verify_kb_integration_status`](#verify_kb_integration_status) | Transcript & KB | No | Check transcript-ingestion subscription status |
| [`start_kb_integration`](#start_kb_integration) | Transcript & KB | Yes | Start automatic transcript ingestion |
| [`stop_kb_integration`](#stop_kb_integration) | Transcript & KB | Yes | Stop automatic transcript ingestion |

**Mutating** means the tool writes data to at least one of the following:

- **Microsoft Teams** — posts a new message to a chat or channel via Microsoft Graph, on behalf of the signed-in user
- **Internal database** — persists or removes state managed by this server (e.g. the transcript-ingestion subscription record)
- **Unique knowledge base** — queues meeting-transcript content for indexing into the knowledge base used by `find_transcripts`

| Tool | What it mutates |
|------|----------------|
| `send_chat_message` | Posts a new plain-text message to the target chat via Microsoft Graph as the signed-in user |
| `send_channel_message` | Posts a new plain-text message to the target channel via Microsoft Graph as the signed-in user |
| `start_kb_integration` | Creates a Microsoft Graph webhook subscription for new transcripts and writes the subscription record to the internal database |
| `stop_kb_integration` | Cancels the Microsoft Graph webhook subscription and removes the subscription record from the internal database |
| `ingest_meeting` | Queues the selected meeting transcript(s) for asynchronous ingestion into the Unique knowledge base |

!!! warning "Chat and channel messages are not ingested"
    The message tools read and write Teams messages live through Microsoft Graph. Unlike meeting transcripts, **chat and channel messages are never copied into the Unique knowledge base** — `get_*_messages` and `search_messages` query Microsoft Graph on every call. Only meeting transcripts are ingested (via `start_kb_integration` / `ingest_meeting`) and searched with `find_transcripts`.

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
| `contentFormat` | `normalized` \| `raw` | No | `normalized` | `normalized` converts HTML to readable text; `raw` returns Teams HTML verbatim. |
| `includeSystemMessages` | boolean | No | `false` | Include event notifications (member added, call ended). |
| `timestampFormat` | `full` \| `short` \| `none` | No | `short` | `full` = ISO 8601 with ms; `short` = `YYYY-MM-DD HH:mm`; `none` = omit timestamps. |
| `detail` | `standard` \| `full` | No | `standard` | `standard` returns sender, content, and timestamp; `full` also adds `contentType` (the source format from Graph). |

**Returns:** The `chatId` and a `messages` array (newest first). Each message has `id`, `senderDisplayName` (nullable), `content`, `createdDateTime` (omitted when `timestampFormat=none`), and `contentType` (only when `detail=full`).

**Example:**

```json
{
  "chatId": "19:1on1@unq.gbl.spaces",
  "messages": [
    {
      "id": "1718901120000",
      "senderDisplayName": "Alice Smith",
      "content": "@Bob Jones can you review the PR? [attachment: design.pdf]",
      "createdDateTime": "2024-06-20 14:32"
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
| `contentFormat` | `normalized` \| `raw` | No | `normalized` | `normalized` converts HTML to readable text; `raw` returns Teams HTML verbatim. |
| `includeSystemMessages` | boolean | No | `false` | Include event notifications (member added, call ended). |
| `timestampFormat` | `full` \| `short` \| `none` | No | `short` | `full` = ISO 8601 with ms; `short` = `YYYY-MM-DD HH:mm`; `none` = omit timestamps. |
| `detail` | `standard` \| `full` | No | `standard` | `standard` returns sender, content, and timestamp; `full` also adds `contentType`. |

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

Search Microsoft Teams messages by keyword across 1:1 chats, group chats, and channels in a single query, using the [Microsoft Search API](https://learn.microsoft.com/en-us/graph/search-concept-overview) (`POST /search/query` on Graph **v1.0**). Supports identity and scope filters. Results are snippets by default; set `detail=full` to hydrate message bodies. At least one search criterion (`query`, `from`, `to`, `mentions`, `sentAfter`, `sentBefore`, `hasAttachment`, `isRead`, or `isMentioned`) must be provided.

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
| `source` | `chat` \| `channel` \| `all` | No | `all` | Filter results by container. Applied after the search, so a non-`all` value shrinks the returned page. |
| `detail` | `summary` \| `full` | No | `summary` | `summary` returns the hit snippet only (1 Graph call). `full` hydrates each hit with its message body (one extra Graph call per hit). |
| `contentFormat` | `normalized` \| `raw` | No | `normalized` | Only applies when `detail=full`. `normalized` converts HTML to readable text; `raw` returns Teams HTML verbatim. |
| `offset` | integer (≥ 0) | No | `0` | Number of results to skip for pagination (maps to Graph `from`). |
| `size` | integer (1–`GRAPH_PAGE_SIZE`) | No | `25` | Maximum number of results per page. |

**Returns:** A `messages` array, `returnedCount` (rows on **this page**, after the `source` filter — not total corpus matches), and `moreResultsAvailable` (paginate with `offset` until this is `false`). Each hit has:

| Field | Description |
|-------|-------------|
| `id` | Message id |
| `source` | `chat` or `channel` (derived from the hit's resource shape) |
| `chatId` | Chat id (present for chat hits, else `null`) |
| `teamId` | Team id (present for channel hits, else `null`) |
| `channelId` | Channel id (present for channel hits, else `null`) |
| `senderDisplayName` | Sender name (nullable) |
| `summary` | Search snippet (nullable) |
| `content` | Hydrated message body — present only when `detail=full` and hydration succeeded |
| `createdDateTime` | Message timestamp (nullable) |
| `webUrl` | Deep link to the message (nullable) |

Pass the returned `chatId` (or `teamId` + `channelId`) straight to `get_*_messages` or `send_*_message`.

!!! note "How `detail=full` hydration behaves"
    Hydration issues one extra Graph call per hit (an N+1 fan-out), capped at 5 concurrent requests to stay throttle-friendly. If an individual hit is forbidden or deleted, that row falls back to summary-only (no `content`) rather than failing the whole page.

**Example:**

```json
{
  "messages": [
    {
      "id": "1718900000000",
      "source": "channel",
      "chatId": null,
      "teamId": "19:abc...@thread.tacv2",
      "channelId": "19:ch1...@thread.tacv2",
      "senderDisplayName": "Carol Lee",
      "summary": "Deploy is <c0>green</c0>.",
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

These tools manage and search **meeting transcripts** ingested into the Unique knowledge base. This is distinct from the message tools above — chat and channel messages are never ingested.

### `find_transcripts`

Search within ingested meeting transcripts using hybrid semantic + keyword search. Returns relevant passages that can be cited with `[N]` notation, where `N` is the result index.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | Search query to match content within transcripts. |
| `subject` | string | No | — | Filter by meeting subject (partial match). |
| `dateFrom` | string (ISO 8601 datetime) | No | — | Only transcripts whose meeting started on or after this datetime. |
| `dateTo` | string (ISO 8601 datetime) | No | — | Only transcripts whose meeting started on or before this datetime. |
| `organizer` | string | No | — | Filter by meeting organizer name or email (partial match). |
| `participant` | string | No | — | Filter by participant name or email (partial match). |
| `limit` | integer (1–100) | No | `10` | Maximum number of results to return. |

**Returns:** A `results` array of passages. Each has `id` (content id), `chunkId`, `title`, `key`, `text` (the passage), `url` (`unique://content/{id}`), `meetingDate`, `startDatetime`, `endDatetime`, `organizer`, and `participants`. Cite a passage with `[N]` where `N` is its array index.

**Example:**

```json
{
  "results": [
    {
      "id": "cont_abc123",
      "title": "Q2 Planning",
      "text": "We agreed to ship the connector in July...",
      "url": "unique://content/cont_abc123",
      "meetingDate": "2024-06-01T10:00:00Z",
      "organizer": "Alice Smith",
      "participants": ["Alice Smith", "Bob Jones"]
    }
  ]
}
```

---

### `list_meetings`

Browse ingested meetings without a search query. Use this to discover meetings by date range, organizer, participant, or subject; then use `find_transcripts` to search within them.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `dateFrom` | string (ISO 8601 datetime) | No | — | Meetings that started on or after this datetime. |
| `dateTo` | string (ISO 8601 datetime) | No | — | Meetings that started on or before this datetime. |
| `organizer` | string | No | — | Filter by organizer name or email (partial match). |
| `participant` | string | No | — | Filter by participant name or email (partial match). |
| `subject` | string | No | — | Filter by meeting subject (partial match). |
| `skip` | integer (≥ 0) | No | `0` | Number of results to skip (pagination). |
| `take` | integer (1–50) | No | `20` | Maximum number of meetings to return. |

**Returns:** A `meetings` array and `total` (number of matching meetings). Each meeting has `id` (content id — reference it in other tools), `title`, `meetingDate`, `startDatetime`, `endDatetime`, `organizer`, and `participants`.

**Example:**

```json
{
  "meetings": [
    {
      "id": "cont_abc123",
      "title": "Q2 Planning",
      "meetingDate": "2024-06-01T10:00:00Z",
      "organizer": "Alice Smith",
      "participants": ["Alice Smith", "Bob Jones"]
    }
  ],
  "total": 1
}
```

---

### `ingest_meeting`

Ingest a specific Teams meeting's transcript on demand, identified by its join URL. Use this to ingest a meeting that predates the knowledge-base integration, or to re-pull a single occurrence. You must be the organizer or an invited attendee. Ingestion runs asynchronously; the tool returns once the transcript is queued.

!!! note "Interactive transcript selection"
    When a recurring meeting has multiple transcripts and no `date` is given, the tool prompts the user to choose via MCP elicitation. If the client does not support elicitation, pass an explicit `date` (`YYYY-MM-DD`).

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `joinUrl` | string (URL) | Yes | — | The Teams meeting join URL (`joinWebUrl`). You must be the organizer or an invited attendee. |
| `date` | string (ISO date) | No | — | Day (`YYYY-MM-DD`, UTC) to pick a transcript when a recurring meeting has several. |

**Returns:** `success`, a human-readable `message`, `meeting` (`id`, `subject`, `joinUrl` — or `null` if not found), and `queued` (array of `{ transcriptId, createdDate }` for each transcript queued for ingestion).

**Example:**

```json
{
  "success": true,
  "message": "Queued 1 transcript(s) for ingestion. They will appear in the knowledge base shortly.",
  "meeting": { "id": "MSo...", "subject": "Q2 Planning", "joinUrl": "https://teams.microsoft.com/l/meetup-join/..." },
  "queued": [{ "transcriptId": "MSMjMCMj...", "createdDate": "2024-06-01T10:05:00.000Z" }]
}
```

---

### `verify_kb_integration_status`

Check the status of the transcript-ingestion knowledge-base integration: whether automatic ingestion is active, expiring soon, expired, or not configured.

**Input parameters:** None

**Returns:** `status` (`active` \| `expiring_soon` \| `expired` \| `not_configured`), a `message`, and `subscription` (`id`, `expiresAt`, `minutesUntilExpiration`, `createdAt`, `updatedAt` — or `null` when not configured).

| Status | Meaning | Action |
|--------|---------|--------|
| `active` | Ingestion subscription is valid | None required |
| `expiring_soon` | Expires within 15 minutes | Renewal is automatic; no action needed |
| `expired` | Subscription has lapsed | Call `start_kb_integration` |
| `not_configured` | No subscription exists | Call `start_kb_integration` |

---

### `start_kb_integration`

Start automatic ingestion of meeting transcripts into the knowledge base. Creates a Microsoft Graph webhook subscription so new transcripts are ingested as they become available. Safe to call when already active — it returns `already_active` without creating a duplicate.

**Input parameters:** None

**Returns:** `success`, a `message`, and `subscription` (`id`, `expiresAt`, `minutesUntilExpiration`, `status` — one of `created`, `already_active`, `expiring_soon`).

---

### `stop_kb_integration`

Stop automatic ingestion of meeting transcripts. Removes the Microsoft Graph webhook subscription; previously ingested transcripts remain in the knowledge base.

**Input parameters:** None

**Returns:** `success`, a `message`, and `subscription` (`id`, `status` — `removed` or `not_found` — or `null` when nothing was active).

---

## Related Documentation

- [Architecture](./architecture.md) - System components, including the chat and transcript modules
- [Flows](./flows.md) - Sequence diagrams for the read, search, send, and transcript flows
- [Subscription Management](./subscription-management.md) - Lifecycle behind `start_kb_integration` / `stop_kb_integration` / `verify_kb_integration_status`
- [Permissions](./permissions.md) - Microsoft Graph permissions required by these tools
- [Security](./security.md) - Token isolation, delegated access, and the message-send write surface
</content>
</invoke>
