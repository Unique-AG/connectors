# Add cursor-based pagination to `get_chat_messages`

## Context

The tool currently fetches a single window of messages with no way to retrieve earlier history. The Graph API returns `@odata.nextLink` on paginated responses. This is a full, ready-to-use URL that encodes all original query parameters (filters, ordering, page size). Exposing it as a `pageToken` input allows callers to walk back through conversation history page by page without reconstructing the original query.

This is the standard Teams Graph API pagination pattern: call with parameters the first time, receive a `nextLink` URL, pass it verbatim as `pageToken` on the next call.

## Behaviour

### First call (no pageToken)

```
Input:  { chatIdentifier: "Alice", limit: 20 }
Output: { text: "Chat: Alice (20 messages)\n\n2024-01-16\n[09:05] ...\n\n[Showing last 20 messages. Use pageToken=\"https://graph.microsoft.com/v1.0/chats/19:abc.../messages?$skip=20&$top=20\" to retrieve earlier messages.]",
          nextPageToken: "https://graph.microsoft.com/v1.0/chats/19:abc.../messages?$skip=20&$top=20" }
```

### Subsequent call (with pageToken)

```
Input:  { chatIdentifier: "Alice", pageToken: "https://graph.microsoft.com/v1.0/chats/19:abc.../messages?$skip=20&$top=20" }
Output: { text: "Chat: Alice (20 messages)\n\n2024-01-15\n[14:30] ...",
          nextPageToken: null }
```

### pageToken bypass behaviour

When `pageToken` is present, the service **completely skips** the standard query-building chain (`.top()`, `.orderby()`, `.select()`, `.filter()`). It calls `client.api(pageToken).get()` directly. The `nextLink` URL already encodes all of those parameters from the original request.

Because of this, when `pageToken` is present, the `since`, `before`, and `order` parameters in the current request are ignored silently — the cursor encodes the original query's constraints. Document this in the parameter description.

### Hard cap on limit

If `input.limit > 200`, the service throws a `BadRequestException` with message `"limit must not exceed 200"` before making any Graph API call. This cap exists because large fetches against the Teams API are slow and the response would exceed typical LLM context windows.

### Zod mutual exclusivity

Add a `.refine()` to `GetChatMessagesInputSchema` that rejects requests where `pageToken` is set at the same time as `since` or `before`:

```typescript
.refine(
  (data) => !(data.pageToken && (data.since || data.before)),
  { message: 'pageToken is mutually exclusive with since and before; the cursor encodes the original query' },
)
```

`order` does not need to be in the refine — it is simply ignored when `pageToken` is present, and that is acceptable (order is already baked into the cursor).

### Footer line in transcript

When `nextPageToken` is non-null, the last line of the `text` field is:

```
[Showing last 50 messages. Use pageToken="<nextPageToken>" to retrieve earlier messages.]
```

When `nextPageToken` is null, no footer line appears.

The footer is separated from the last date block by one blank line.

## Implementation

### `services/teams-mcp/src/chat/tools/get-chat-messages.tool.ts`

**Input schema** — add two fields to `GetChatMessagesInputSchema`:

```typescript
pageToken: z
  .string()
  .optional()
  .describe(
    'Cursor returned as nextPageToken from a previous call. When provided, fetches the next page of the same query. Mutually exclusive with since and before.',
  ),
```

The `limit` field upper bound changes from `.max(50)` to `.max(200)`. The default stays `20`.

Add the mutual exclusivity `.refine()` after the `.object({...})` definition:

```typescript
const GetChatMessagesInputSchema = z.object({
  // ... all fields ...
}).refine(
  (data) => !(data.pageToken && (data.since || data.before)),
  { message: 'pageToken is mutually exclusive with since and before' },
);
```

**Output schema** — add `nextPageToken` to `GetChatMessagesOutputSchema`:

```typescript
const GetChatMessagesOutputSchema = z.object({
  text: z.string(),
  nextPageToken: z.string().nullable(),
});
```

**Tool method** — thread `pageToken` through to the service call and include `nextPageToken` in the return:

```typescript
const { messages, nextPageToken } = await this.chatService.getChatMessages(
  userProfileId,
  chat.id,
  input.limit,
  { pageToken: input.pageToken, order: input.order, since: input.since, before: input.before },
);

// ...filter...

return {
  text: this.renderTranscript(chat, filtered, input, nextPageToken),
  nextPageToken,
};
```

**`renderTranscript`** — add `nextPageToken: string | null` as a fourth parameter. Append the footer when non-null:

```typescript
if (nextPageToken) {
  parts.push(
    `[Showing last ${sorted.length} messages. Use pageToken="${nextPageToken}" to retrieve earlier messages.]`,
  );
}
return parts.join('\n\n');
```

### `services/teams-mcp/src/chat/chat.service.ts`

Update `getChatMessages` signature:

```typescript
public async getChatMessages(
  userProfileId: string,
  chatId: string,
  limit: number,
  options: {
    pageToken?: string;
    order?: 'newest' | 'oldest';
    since?: string;
    before?: string;
  } = {},
): Promise<{ messages: MsChatMessage[]; nextPageToken: string | null }>
```

**Hard cap check** — at the top of the method, before any Graph API calls:

```typescript
if (limit > 200) {
  throw new BadRequestException('limit must not exceed 200');
}
```

**pageToken path** — when `options.pageToken` is set, bypass all query building:

```typescript
if (options.pageToken) {
  const response = await client.api(options.pageToken).get();
  const messages = z.array(MsChatMessageSchema).parse(response.value);
  return {
    messages,
    nextPageToken: (response['@odata.nextLink'] as string | undefined) ?? null,
  };
}
```

**Standard path** — when no pageToken, build the query normally (chaining `.top()`, `.orderby()`, `.select()`, `.filter()` as added by the order-and-time-range ticket) and extract `nextPageToken` from the response:

```typescript
const response = await client
  .api(`/chats/${chatId}/messages`)
  .top(limit)
  .orderby(orderByClause)
  .select('id,createdDateTime,from,body,attachments,messageType')
  // .filter(...) conditionally added
  .get();

const messages = z.array(MsChatMessageSchema).parse(response.value);
return {
  messages,
  nextPageToken: (response['@odata.nextLink'] as string | undefined) ?? null,
};
```

Note: `response['@odata.nextLink']` is a full URL string like `https://graph.microsoft.com/v1.0/chats/{id}/messages?$skip=20&$top=20`. It is safe to pass directly to `client.api(url).get()`.

## Acceptance Criteria

- `GetChatMessagesInputSchema` includes `pageToken: z.string().optional()`.
- `GetChatMessagesOutputSchema` includes `nextPageToken: z.string().nullable()`.
- Tool input `limit` accepts values up to 200; values above 200 are rejected by a `BadRequestException` with message `"limit must not exceed 200"` before any Graph API call is made.
- When `pageToken` is provided, `ChatService.getChatMessages` calls `client.api(pageToken).get()` directly without chaining `.top()`, `.orderby()`, `.select()`, or `.filter()`.
- When `pageToken` is provided alongside `since` or `before`, Zod validation rejects the input with the mutual exclusivity error message.
- `nextPageToken` in the response is `null` when the Graph API response does not include `@odata.nextLink`.
- `nextPageToken` in the response is the full `@odata.nextLink` URL string when more pages exist.
- The transcript `text` field includes the footer line `[Showing last N messages. Use pageToken="..." to retrieve earlier messages.]` when `nextPageToken` is non-null.
- The transcript `text` field has no footer line when `nextPageToken` is null.
- Pagination works end-to-end: passing the `nextPageToken` from response N as `pageToken` in request N+1 retrieves the subsequent page of messages.
- The service return type changes from `Promise<MsChatMessage[]>` to `Promise<{ messages: MsChatMessage[]; nextPageToken: string | null }>` — all call sites in the tool layer are updated accordingly.
