# Replace JSON output with IRC-style transcript format in `get_chat_messages`

## Context

The current `get_chat_messages` tool returns a JSON object with `chatId`, `chatTopic`, and a `messages` array. For the primary use case — reading, summarising, or reasoning about a conversation — this structure is wasteful. Wrapping every message in JSON keys uses tokens that contribute nothing to comprehension.

An IRC-style plain text transcript is dramatically more token-efficient: a 50-message conversation that takes ~3,000 tokens as JSON takes ~900 tokens as text. It is also more natural for the LLM to reason over.

The JSON output format is being **removed entirely**. There is no `format` parameter. The IRC text transcript is the only output.

## Behaviour

### Output format specification

The tool returns a single string in the `text` field of its output.

**Full example with all features:**

```
Chat: Project Standup (12 messages)

2024-01-15
[14:30] Alice Smith: Hey, can we move the standup to 10am tomorrow?
[14:31] Bob Jones: Sure, works for me
── Carol White joined the chat ──
[14:33] Carol White: I have a conflict, can we do 10:15?

2024-01-16
[09:05] Alice Smith: 10:15 confirmed, updating the invite

[Showing last 50 messages. Use pageToken="https://graph.microsoft.com/v1.0/..." to retrieve earlier messages.]
```

**Rules:**

1. **Header line**: `Chat: <chatTopic> (<N> messages)` where `<N>` is the count of messages in the returned set (after filtering). If the chat has no topic (`chat.topic` is undefined or null), use the chat ID: `Chat: <chatId> (<N> messages)`.

2. **Date groups**: Messages are grouped by calendar date. Each group starts with a `YYYY-MM-DD` date line. There is one blank line between date groups. There is no blank line between the header and the first date group.

3. **Regular messages**: `[HH:MM] Sender Name: message content`
   - `HH:MM` is extracted from the ISO 8601 `createdDateTime` string (e.g. `"2024-01-15T14:30:45.000Z"` → `"14:30"`). No timezone indicator is shown. Use the UTC time as returned by the Graph API.
   - `Sender Name` is `m.senderDisplayName`. If `senderDisplayName` is undefined or null, use `Unknown`.
   - `message content` is the result of `normalizeContent(m.content, m.contentType, m.attachments)` — always normalized, never raw HTML.

4. **System messages** (only when `includeSystemMessages: true`): `── <description> ──` on its own line, not prefixed with a timestamp or sender. The description comes from `renderSystemMessage(m.eventDetail)` (implemented in the system-message-rendering ticket; before that ticket lands, use `normalizeContent(m.content, m.contentType, m.attachments)` as the description).

5. **Message IDs** (only when `includeMessageIds: true`): append ` [id:<messageId>]` to the end of each regular message line:
   ```
   [14:30] Alice Smith: Hey, can we move the standup to 10am tomorrow? [id:1715788200000]
   ```
   System message lines never get an ID annotation.

6. **Footer line**: Shown only when `nextPageToken` is non-null (see cursor-pagination ticket):
   ```
   [Showing last 50 messages. Use pageToken="<token>" to retrieve earlier messages.]
   ```
   When there is no next page, omit the footer entirely. When pagination is not yet implemented, this line never appears.

7. **Display order**: Messages are always rendered oldest-first (ascending `createdDateTime`) regardless of the fetch order. After fetching, sort by `createdDateTime` ascending before rendering.

### Parameters removed

The following input parameters are removed from the schema entirely:
- `timestampFormat` — the IRC format always uses `HH:MM`; no alternatives are offered.
- `detail` — the `contentType` field is internal plumbing not relevant to transcript reading.
- `contentFormat` — content is always normalized through `normalizeContent`.

### Parameters kept

- `chatIdentifier: z.string()` — unchanged
- `limit: z.number().int().min(1).max(50).default(20)` — unchanged (will be expanded in the cursor-pagination ticket)
- `includeSystemMessages: z.boolean().default(false)` — unchanged
- `includeMessageIds: z.boolean().default(false)` — **new parameter** added in this ticket

### Output schema

`GetChatMessagesOutputSchema` is removed entirely and replaced with:

```typescript
const GetChatMessagesOutputSchema = z.object({
  text: z.string(),
});
```

The `nextPageToken` field (`z.string().nullable()`) will be added alongside `text` in the cursor-pagination ticket. For now, the schema is exactly `{ text: z.string() }`.

The tool return type is `Promise<{ text: string }>`.

## Implementation

### `services/teams-mcp/src/chat/tools/get-chat-messages.tool.ts`

**Input schema** — replace the current `GetChatMessagesInputSchema` with:

```typescript
const GetChatMessagesInputSchema = z.object({
  chatIdentifier: z.string().describe('Chat topic or member display name (case-insensitive)'),
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .default(20)
    .describe('Maximum number of messages to return. Default: 20'),
  includeSystemMessages: z
    .boolean()
    .default(false)
    .describe(
      'Include system event notifications (member added, call ended, etc.). Default: false',
    ),
  includeMessageIds: z
    .boolean()
    .default(false)
    .describe(
      'Append [id:<messageId>] to each message line. Useful when a downstream action needs to reference a specific message. Default: false',
    ),
});
```

**Output schema** — replace `GetChatMessagesOutputSchema` with:

```typescript
const GetChatMessagesOutputSchema = z.object({
  text: z.string(),
});
```

**Tool decorator** — update `description`:

```
"Retrieve messages from a Microsoft Teams chat as an IRC-style plain text transcript. Messages are grouped by date and formatted as [HH:MM] Sender: content. Use list_chats first if you don't know the chat identifier."
```

**Tool method** — replace `return { chatId, chatTopic, messages: filtered.map(...) }` with a call to a new private method:

```typescript
return { text: this.renderTranscript(chat, filtered, input) };
```

**Remove** the `mapMessage` private method entirely.

**Add** a new private `renderTranscript` method:

```typescript
private renderTranscript(
  chat: MsChat,
  messages: MsChatMessage[],
  input: z.infer<typeof GetChatMessagesInputSchema>,
): string {
  // Sort ascending for display regardless of fetch order
  const sorted = [...messages].sort(
    (a, b) => new Date(a.createdDateTime).getTime() - new Date(b.createdDateTime).getTime(),
  );

  const header = `Chat: ${chat.topic ?? chat.id} (${sorted.length} messages)`;

  // Group by date
  const groups = new Map<string, MsChatMessage[]>();
  for (const m of sorted) {
    const date = m.createdDateTime.slice(0, 10); // 'YYYY-MM-DD'
    const group = groups.get(date) ?? [];
    group.push(m);
    groups.set(date, group);
  }

  const dateBlocks: string[] = [];
  for (const [date, msgs] of groups) {
    const lines: string[] = [date];
    for (const m of msgs) {
      if (m.messageType === 'message') {
        const time = m.createdDateTime.slice(11, 16); // 'HH:MM'
        const sender = m.senderDisplayName ?? 'Unknown';
        const content = normalizeContent(m.content, m.contentType, m.attachments);
        const idSuffix = input.includeMessageIds ? ` [id:${m.id}]` : '';
        lines.push(`[${time}] ${sender}: ${content}${idSuffix}`);
      } else if (input.includeSystemMessages) {
        // Before system-message-rendering ticket: use normalizeContent as fallback
        const description = normalizeContent(m.content, m.contentType, m.attachments);
        lines.push(`── ${description} ──`);
      }
    }
    dateBlocks.push(lines.join('\n'));
  }

  return [header, ...dateBlocks].join('\n\n');
}
```

Note: `nextPageToken` footer line rendering is added in the cursor-pagination ticket.

### `services/teams-mcp/src/chat/chat.dtos.ts`

No changes in this ticket. The `MsChatMessageSchema` gains `messageType` from the fix-system-message-detection ticket, which this rendering code depends on.

## Acceptance Criteria

- `GetChatMessagesInputSchema` does not contain `timestampFormat`, `detail`, or `contentFormat` fields.
- `GetChatMessagesInputSchema` contains `includeMessageIds: z.boolean().default(false)`.
- `GetChatMessagesOutputSchema` is `z.object({ text: z.string() })` — no `chatId`, `chatTopic`, or `messages` fields.
- The tool method returns `{ text: string }` — the text field contains the full transcript.
- The transcript header is `Chat: <topic> (<N> messages)` using the chat topic; falls back to chat ID when topic is absent.
- Messages are grouped by calendar date (`YYYY-MM-DD`), with date headers and blank lines between groups.
- Each regular message line is formatted as `[HH:MM] Sender Name: normalized content`.
- When `includeSystemMessages: false` (default), no system message lines appear in the transcript.
- When `includeSystemMessages: true`, system messages render as `── <description> ──` interspersed in chronological order.
- When `includeMessageIds: true`, each regular message line ends with ` [id:<messageId>]`.
- Messages are always displayed oldest-first regardless of `order` parameter (order controls fetch; display is always ascending).
- The `mapMessage` private method no longer exists in the file.
- The tool description in the `@Tool` decorator references the IRC-style transcript format.
- No regression in the other 5 tools.
