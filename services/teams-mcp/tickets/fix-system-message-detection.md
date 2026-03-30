# Fix system message detection to use `messageType` field

## Context

`get_chat_messages` currently filters out system messages using `senderDisplayName !== undefined` as a proxy. This is fragile for two reasons:

1. Regular bot or application messages can have a non-null `from.application` but no `from.user`, making `senderDisplayName` undefined even though the message is a normal message, not a system event.
2. The `from` field can be null on system messages, but that is incidental — it is not the canonical discriminator.

The Graph API returns a `messageType` field on every chat message with one of three values: `"message"`, `"systemEventMessage"`, or `"chatEvent"`. This is the correct field to use. The fix changes the detection logic, adds `messageType` to the DTO schema, and adds it to the `$select` string in the service.

## Behaviour

### Current (broken) behaviour

```
messages.filter((m) => m.senderDisplayName !== undefined)
```

A message from a bot (`from.application` set, `from.user` null) would be excluded even though it is a regular message. A future Graph API change to populate `from` on system events would cause system events to leak through.

### Fixed behaviour

```
messages.filter((m) => m.messageType === 'message')
```

The `messageType === 'message'` check is exact and stable. System event messages have `messageType === 'systemEventMessage'`; Teams lifecycle notifications have `messageType === 'chatEvent'`. Both are excluded when `includeSystemMessages: false`, and both pass through when `includeSystemMessages: true`.

### Graph API note

`messageType` is always present in the response — it is a required field in the Graph API schema. It does not need to be optional in the Zod schema.

The current `$select` in `getChatMessages` is:
```
'id,createdDateTime,from,body,attachments'
```
After this fix it becomes:
```
'id,createdDateTime,from,body,attachments,messageType'
```

## Implementation

### `services/teams-mcp/src/chat/chat.dtos.ts`

In `MsChatMessageSchema`, add `messageType` as a non-optional field **before** the `.transform()` call, between `attachments` and the closing `})`:

```typescript
// before .transform(...)
messageType: z.enum(['message', 'systemEventMessage', 'chatEvent']),
```

The `.transform()` callback currently produces:
```typescript
{
  id: msg.id,
  createdDateTime: msg.createdDateTime,
  senderDisplayName: ...,
  content: msg.body.content,
  contentType: msg.body.contentType,
  attachments: ...,
}
```

Update it to also pass through `messageType`:
```typescript
{
  id: msg.id,
  createdDateTime: msg.createdDateTime,
  messageType: msg.messageType,           // ← add this line
  senderDisplayName: ...,
  content: msg.body.content,
  contentType: msg.body.contentType,
  attachments: ...,
}
```

The inferred `MsChatMessage` type (via `z.infer<typeof MsChatMessageSchema>`) will now include `messageType: 'message' | 'systemEventMessage' | 'chatEvent'`.

### `services/teams-mcp/src/chat/chat.service.ts`

In `getChatMessages`, change the `.select(...)` chain call from:
```typescript
.select('id,createdDateTime,from,body,attachments')
```
to:
```typescript
.select('id,createdDateTime,from,body,attachments,messageType')
```

No other changes to `chat.service.ts`.

### `services/teams-mcp/src/chat/tools/get-chat-messages.tool.ts`

Change the filter expression in `getChatMessages` (the tool method, not the service):

Before (line 116–118):
```typescript
const filtered = input.includeSystemMessages
  ? messages
  : messages.filter((m) => m.senderDisplayName !== undefined);
```

After:
```typescript
const filtered = input.includeSystemMessages
  ? messages
  : messages.filter((m) => m.messageType === 'message');
```

No other changes to the tool file as part of this ticket.

## Acceptance Criteria

- `MsChatMessageSchema` in `chat.dtos.ts` includes `messageType: z.enum(['message', 'systemEventMessage', 'chatEvent'])` as a required field in the pre-transform object shape.
- The `.transform()` output of `MsChatMessageSchema` includes `messageType` — calling `z.infer<typeof MsChatMessageSchema>` on a parsed value exposes `messageType` as a non-optional string union.
- `getChatMessages` in `chat.service.ts` requests `messageType` in the Graph API `$select` string.
- With `includeSystemMessages: false` (default), only messages where `messageType === 'message'` are returned. Messages where `messageType === 'systemEventMessage'` or `messageType === 'chatEvent'` are excluded.
- With `includeSystemMessages: true`, all messages are returned regardless of `messageType`.
- A message from a bot application (`from.user` null, `from.application` set) is included when `includeSystemMessages: false` — it is a regular message, not a system event.
- No changes to any other tool (`list_chats`, `send_chat_message`, `send_channel_message`, `list_teams`, `list_channels`).
- If the Graph API returns an unknown `messageType` value, Zod parsing throws with a descriptive error (enum mismatch) rather than silently producing bad data.
