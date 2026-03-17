# Add `order` and time-range parameters to `get_chat_messages`

## Context

Without ordering and time-range controls, the tool can only fetch the most recent N messages with no ability to scope a query to a relevant window. Two common use cases are blocked:

1. **Daily summaries**: "What was discussed in this channel today?" — requires `since: today 00:00` and `before: today 23:59`.
2. **Oldest-first reading**: Summarizing a thread reads more naturally oldest-first. Currently the Graph API is always queried `createdDateTime desc`, so the LLM receives the end of the conversation first.

The Graph API supports `$orderby=createdDateTime asc|desc` and `$filter=createdDateTime ge <ISO> and createdDateTime le <ISO>` on the `/chats/{id}/messages` endpoint.

## Behaviour

### `order` parameter

Controls which end of the conversation history is fetched when combined with `limit`. It does **not** control display order — the IRC transcript always displays messages oldest-first (ascending) regardless. Sort ascending by `createdDateTime` before rendering.

- `order: 'newest'` (default): query with `$orderby=createdDateTime desc` → fetches the most recent N messages → display re-sorted ascending
- `order: 'oldest'`: query with `$orderby=createdDateTime asc` → fetches the oldest N messages → already ascending

### `since` and `before` parameters

Both are optional ISO 8601 datetime strings validated by Zod's `.datetime()`. They map to Graph API `$filter` clauses:

- `since` only → `$filter=createdDateTime ge <since>`
- `before` only → `$filter=createdDateTime le <before>`
- Both → `$filter=createdDateTime ge <since> and createdDateTime le <before>`
- Neither → no `$filter` applied

The filter string is built conditionally in the service before calling `.filter()` on the Graph client. Only call `.filter()` when at least one of `since`/`before` is present.

### Interaction of order + time range

| order | since | before | Effect |
|-------|-------|--------|--------|
| newest | set | — | Fetches the most recent N messages that are newer than `since` |
| newest | — | set | Fetches the most recent N messages that are older than `before` |
| oldest | set | — | Fetches the oldest N messages starting from `since` forward |
| oldest | — | set | Fetches the oldest N messages up to `before` |
| newest | set | set | Fetches the most recent N messages within the window |
| oldest | set | set | Fetches the oldest N messages within the window |

### Interaction with pageToken

When `pageToken` is provided (cursor-pagination ticket), `order`, `since`, and `before` are ignored — the cursor already encodes the original query's parameters. The Zod `.refine()` in the cursor-pagination ticket handles the `pageToken + since/before` mutual exclusion case. `order` + `pageToken` together is allowed but `order` is silently ignored.

### Display order invariant

Regardless of which `order` value was used to fetch, the transcript always shows messages sorted ascending by `createdDateTime`. This means:

- With `order: 'newest'` the service returns messages newest-first; `renderTranscript` sorts them ascending before building the date groups.
- With `order: 'oldest'` the service returns messages oldest-first; they are already in the right display order but `renderTranscript` still sorts (idempotent, cheap).

## Implementation

### `services/teams-mcp/src/chat/tools/get-chat-messages.tool.ts`

Add to `GetChatMessagesInputSchema`:

```typescript
order: z
  .enum(['newest', 'oldest'])
  .default('newest')
  .describe(
    'newest (default) fetches the most recent messages; oldest fetches from the beginning. The transcript always displays oldest-first regardless.',
  ),
since: z
  .string()
  .datetime()
  .optional()
  .describe('ISO 8601 datetime. Only return messages at or after this time.'),
before: z
  .string()
  .datetime()
  .optional()
  .describe('ISO 8601 datetime. Only return messages at or before this time.'),
```

Thread all three through to `ChatService.getChatMessages` via the `options` object introduced in the cursor-pagination ticket:

```typescript
const { messages, nextPageToken } = await this.chatService.getChatMessages(
  userProfileId,
  chat.id,
  input.limit,
  { pageToken: input.pageToken, order: input.order, since: input.since, before: input.before },
);
```

Update the tool `description` to mention time-range filtering:

```
"Retrieve messages from a Microsoft Teams chat as an IRC-style plain text transcript. Filter by time range using since/before (ISO 8601). Use order='oldest' to read from the beginning. Use list_chats first if you don't know the chat identifier."
```

### `services/teams-mcp/src/chat/chat.service.ts`

The `options` object (introduced in the cursor-pagination ticket) already includes `order`, `since`, and `before`. Implement the filter and ordering logic in the standard (non-pageToken) path:

```typescript
// Map order to Graph API orderby string
const orderByClause = options.order === 'oldest'
  ? 'createdDateTime asc'
  : 'createdDateTime desc';

// Build filter string
const filterParts: string[] = [];
if (options.since) filterParts.push(`createdDateTime ge ${options.since}`);
if (options.before) filterParts.push(`createdDateTime le ${options.before}`);
const filterClause = filterParts.join(' and ');

// Build query
let query = client
  .api(`/chats/${chatId}/messages`)
  .top(limit)
  .orderby(orderByClause)
  .select('id,createdDateTime,from,body,attachments,messageType');

if (filterClause) {
  query = query.filter(filterClause);
}

const response = await query.get();
```

Note: the Graph client's `.filter()` method accepts an OData filter string directly. No URL encoding is needed — the SDK handles it.

## Acceptance Criteria

- `GetChatMessagesInputSchema` includes `order: z.enum(['newest', 'oldest']).default('newest')`.
- `GetChatMessagesInputSchema` includes `since: z.string().datetime().optional()`.
- `GetChatMessagesInputSchema` includes `before: z.string().datetime().optional()`.
- Passing a non-ISO-8601 string to `since` or `before` (e.g. `"yesterday"`) results in a Zod validation error before any Graph API call is made.
- With `order: 'newest'` (default), the Graph API is called with `$orderby=createdDateTime desc`.
- With `order: 'oldest'`, the Graph API is called with `$orderby=createdDateTime asc`.
- With only `since` set, the Graph API `$filter` is `createdDateTime ge <since>` (no `le` clause).
- With only `before` set, the Graph API `$filter` is `createdDateTime le <before>` (no `ge` clause).
- With both set, the Graph API `$filter` is `createdDateTime ge <since> and createdDateTime le <before>`.
- With neither set, no `$filter` is added to the Graph API query.
- The IRC transcript always renders messages oldest-first regardless of `order` value.
- When `pageToken` is provided, `order`/`since`/`before` are ignored (the cursor encodes the original query); no error is raised.
- `since` and `before` with `pageToken` together trigger the mutual exclusivity Zod refine error (handled in cursor-pagination ticket).
- Omitting all three new parameters produces identical behavior to the current implementation.
