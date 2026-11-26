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

The ids are internal. The tool descriptions, output schemas and server instructions tell the agent to pass them between tools unchanged but never show them to the user. A chat list shows the topic or members, the type and the last-message date, numbered so the user can pick an entry by number. The last-message preview is added only when two chats would otherwise read the same.

### Citations

Every message that `get_chat_messages`, `get_channel_messages` and `search_messages` return carries a `title` and a `webUrl`. A chat message the server reads from Graph always has a link: the one Graph sends, else the chat deep link. A channel post has the link Graph sends, or `null` when Graph sends none. A `search_messages` row whose message could not be fetched has `null` too when it has neither a message id to build the deep link from nor an index link. Conduct (`unique-cli mcp`) cites each message that has an http(s) `webUrl` by its title, with that link, so a channel post without a link is not cited. `list_teams`, `list_chats` and `list_channels` are not cited: they are lookup steps the agent uses to find the messages. The tools send the module's default content, one JSON text item of the output, so Unique AI does not cite them.

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

`limit` is a page size, and the page is 25. Graph serves **at most 25 chats per response**, however large the `$top`, because this call expands the `members` of each chat — a documented limitation of `/me/chats` (see [chat-list](https://learn.microsoft.com/en-us/graph/api/chat-list?view=graph-rest-1.0&tabs=http)), which also behaves differently in some national clouds. One call is one Graph request.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer (1–25) | No | `25` | Page size: how many chats to return. 25 is the most Graph serves in one response. |
| `includeMemberEmails` | boolean | No | `false` | Include member email addresses (only for topic-less chats). Useful when two members share a display name. |

**Returns:** A `chats` array. Each chat has `chatId`, `chatType`, `topic` (nullable), `createdDateTime`, `lastMessageAt`, `lastMessagePreview`, and — for chats without a topic — a `members` array (`displayName`, plus `email` when `includeMemberEmails` is `true`). Pass `chatId` to `get_chat_messages` or `send_chat_message`.

`lastMessagePreview` is the plain text of the last message, with Teams HTML flattened. It is at most 150 characters: longer text is cut and ends in `…`, which counts toward the 150. It is `null` when the last message is deleted, a system event, or has no text (an attachment alone). It lets the agent tell apart chats that have no topic and no named members.

**Example:**

```json
{
  "chats": [
    {
      "chatId": "19:meeting_xyz@thread.v2",
      "chatType": "meeting",
      "topic": "Weekly Sync",
      "createdDateTime": "2024-01-10T08:00:00Z",
      "lastMessageAt": "2024-06-20T14:32:00Z",
      "lastMessagePreview": "Notes from today are in the channel."
    },
    {
      "chatId": "19:1on1@unq.gbl.spaces",
      "chatType": "oneOnOne",
      "topic": null,
      "createdDateTime": "2023-11-02T10:00:00Z",
      "lastMessageAt": "2024-06-19T09:15:00Z",
      "lastMessagePreview": "See you tomorrow",
      "members": [{ "displayName": "Alice Smith" }]
    }
  ]
}
```

---

## Messages

Both `get_*_messages` tools return the body exactly as Graph gives it: `body.contentType` plus the raw `body.content`, which is usually Teams HTML. Nothing is rewritten and no placeholder text is invented. The structured metadata — `mentions`, `attachments`, `reactions`, `deletedDateTime`, `replyToId`, `channelIdentity` — is returned alongside, so a caller reads those instead of parsing the body.

Each message also carries a `title` and a `webUrl`, so a client can cite it. `title` is not a Graph field: the server derives it. Chat messages rarely have a subject, so `title` is the subject when there is one, and otherwise the sender's name and the first 80 characters of the text (`Carol Lee: Deploy is green.`). It is `null` only for an event with neither. `webUrl` opens the message in Teams. Graph normally sends one. A chat message that arrives without one gets the documented deep link `https://teams.microsoft.com/l/message/<chatId>/<messageId>?context={"contextType":"chat"}`. A channel post gets no fallback: its `webUrl` is `null` when Graph sends none.

### `get_chat_messages`

Retrieve recent messages from a chat, identified by `chatId`. Call `list_chats` (or `search_messages`) first to find the `chatId`.

**Input parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `chatId` | string | Yes | — | Exact chat id from `list_chats` or `search_messages`. |
| `limit` | integer (1–50) | No | `20` | Maximum number of messages to return (newest first). |
| `includeSystemMessages` | boolean | No | `false` | Include event notifications (member added, call ended). |

**Returns:** The `chatId` and a `messages` array (newest first). Each message carries `id`, `title`, `messageType`, `subject`, `body` (`contentType` + raw `content`), `from`, `createdDateTime`, `lastModifiedDateTime`, `lastEditedDateTime`, `deletedDateTime`, `importance`, `locale`, `webUrl`, `etag`, `replyToId`, `channelIdentity`, `mentions`, `reactions` and `attachments`.

**Example:**

```json
{
  "chatId": "19:1on1@unq.gbl.spaces",
  "messages": [
    {
      "id": "1718901120000",
      "title": "Alice Smith: Bob Jones can you review the PR?",
      "messageType": "message",
      "subject": null,
      "body": { "contentType": "html", "content": "<p><at id=\"0\">Bob Jones</at> can you review the PR?</p>" },
      "from": { "id": "user-alice", "displayName": "Alice Smith" },
      "createdDateTime": "2024-06-20T14:32:07.113Z",
      "lastModifiedDateTime": "2024-06-20T14:32:07.113Z",
      "lastEditedDateTime": null,
      "deletedDateTime": null,
      "importance": "normal",
      "locale": "en-us",
      "webUrl": "https://teams.microsoft.com/l/message/19%3A1on1%40unq.gbl.spaces/1718901120000?context=%7B%22contextType%22%3A%22chat%22%7D",
      "etag": "1718901120000",
      "replyToId": null,
      "channelIdentity": null,
      "mentions": [
        { "id": 0, "mentionText": "Bob Jones", "mentioned": { "id": "user-bob", "displayName": "Bob Jones" } }
      ],
      "reactions": [],
      "attachments": []
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
      "title": "Carol Lee: Deploy is green.",
      "messageType": "message",
      "subject": null,
      "body": { "contentType": "html", "content": "<p>Deploy is green.</p>" },
      "from": { "id": "user-carol", "displayName": "Carol Lee" },
      "createdDateTime": "2024-06-20T13:50:00.000Z",
      "lastModifiedDateTime": "2024-06-20T13:50:00.000Z",
      "lastEditedDateTime": null,
      "deletedDateTime": null,
      "importance": "normal",
      "locale": "en-us",
      "webUrl": "https://teams.microsoft.com/l/message/19%3Ach1...%40thread.tacv2/1718900000000?groupId=...",
      "etag": "1718900000000",
      "replyToId": null,
      "channelIdentity": { "teamId": "19:abc...@thread.tacv2", "channelId": "19:ch1...@thread.tacv2" },
      "mentions": [],
      "reactions": [],
      "attachments": []
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
| `title` | The fetched message's `title` (see [Messages](#Messages)). For a hit that was not fetched: the sender and the summary as plain text |
| `source` | `chat`, `channel`, or `unknown`. `channel` requires **both** `teamId` and `channelId` on the hit; `chat` requires a `chatId`; anything else is `unknown` and cannot be fetched |
| `chatId` | Chat id (populated only for a `chat` hit, else `null`) |
| `teamId` | Team id (populated only for a `channel` hit, else `null`) |
| `channelId` | Channel id (populated only for a `channel` hit, else `null`) |
| `chatName` | For a `chat` hit, the chat's topic, or its members' names when it has none. `null` for other hits or when the lookup failed |
| `teamName` | For a `channel` hit, the team's display name. `null` otherwise, or when the team is not among the user's joined teams |
| `channelName` | For a `channel` hit, the channel's display name. `null` otherwise, or when the lookup failed |
| `senderDisplayName` | Sender name (nullable). Read from the hit's mailbox identity, which is what the search projection carries, then filled from the hydrated message when the hit named nobody, and as a last resort from the sender's bare email address — so this field can hold an address rather than a name |
| `summary` | Search snippet exactly as Graph returns it, including its `<c0>` hit-highlighting markup (nullable) |
| `message` | The fetched message, exactly as Graph returns it — `body` (`contentType` + raw `content`), plus `mentions`, `attachments`, `reactions`, `deletedDateTime`, `replyToId` and the rest. Absent for an `unknown` hit, a channel reply, or a failed fetch. The row gives no reason code, so an absent `message` does not say which |
| `createdDateTime` | Message timestamp (nullable) |
| `webUrl` | Link to the message (nullable). It can open Outlook rather than Teams. It is the fetched message's link when the message has one, which a chat message always does (Graph's `webUrl`, else the chat-message deep link). Otherwise a `chat` hit that carries both its chat id and its message id gets the deep link built from them. Any other hit, including a chat hit without a message id and a channel post Graph sent no link for, keeps the link from the search index, which Graph documents as an Outlook Web link (`webLink`), though a Teams deep link has been observed |

Pass the returned `chatId` (or `teamId` + `channelId`) straight to `get_*_messages` or `send_*_message`. Show the user `chatName`, or `teamName` and `channelName`, to say where a message was posted, never the ids.

!!! note "How container names are looked up"
    A page of hits spans many chats and channels, and a hit carries only their ids. Each distinct chat is fetched at most once (`GET /chats/{id}?$expand=members`), each distinct channel at most once (`GET /teams/{teamId}/channels/{channelId}`), and every team name comes from one `GET /me/joinedTeams`, made only when the page has a channel hit. At most 3 run at a time, alongside hydration and inside its 15-second budget. A lookup still waiting when the budget is spent is skipped without a request. A failed or skipped lookup leaves the name `null`, and a failed one logs at `warn`. Neither fails the page.

!!! note "How hydration behaves"
    A search hit carries no message body, and Graph offers no way to ask for one. So each hit is fetched on its own: one extra Graph call per hit, at most 3 at a time.

    A hit is fetched by the ids it carries: a message id, plus either both channel ids or a chat id. An `unknown` hit costs no call.

    A failed fetch drops `content` for that row only and logs at `warn`. The page still returns. Two cases always lose the body:

    - **No admin consent for `ChannelMessage.Read.All`.** Every channel hit fails.
    - **A reply inside a channel thread.** Graph addresses a reply under its parent post (`.../messages/{rootId}/replies/{id}`). A search hit does not name that parent, so no id here can fetch it.

    Graph throttles reads of one chat or channel hard, so a page drawn from one busy channel can lose bodies. The whole pass stops after 15 seconds, because the client retries a `429` and honours `Retry-After`, which can take minutes. Remaining hits then return without `content`.

**Example:**

```json
{
  "messages": [
    {
      "id": "1718900000000",
      "title": "Carol Lee: Deploy is green. Rollout finished at 13:49.",
      "source": "channel",
      "chatId": null,
      "teamId": "fbe2bf47-16c8-47cf-b4a5-4b9b187c508b",
      "channelId": "19:ch1...@thread.tacv2",
      "chatName": null,
      "teamName": "Engineering",
      "channelName": "Releases",
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
