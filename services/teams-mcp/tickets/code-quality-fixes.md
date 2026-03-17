# Code quality fixes from PR #344 review

## Context

Several small issues were identified during review of PR #344 that don't warrant individual tickets but should be cleaned up before the feature is considered stable:

1. `MsTeamSchema` and `MsChannelSchema` are identical in shape — duplicated definition with no shared base.
2. `send_channel_message` and `send_chat_message` have no input length validation against Teams API limits, so oversized messages are only rejected at the Graph API layer with a cryptic error.
3. `list-chats.tool.ts` has a redundant `?? LIMIT` null-coalesce that misleads readers into thinking `input.limit` can be undefined.
4. `send_chat_message` returns `{ messageId, chatId }` but `chatId` is already known to the caller from the input — echoing it back wastes tokens.

## Behaviour

### Schema deduplication

`MsTeamSchema` and `MsChannelSchema` currently in `chat.dtos.ts`:

```typescript
export const MsTeamSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  description: z.string().optional(),
});

export const MsChannelSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  description: z.string().optional(),
});
```

They are structurally identical. Introduce a shared base and assign it:

```typescript
const MsEntitySchema = z.object({
  id: z.string(),
  displayName: z.string(),
  description: z.string().optional(),
});

export const MsTeamSchema = MsEntitySchema;
export const MsChannelSchema = MsEntitySchema;
```

The `MsTeam` and `MsChannel` TypeScript types remain unchanged in shape — both equal `z.infer<typeof MsEntitySchema>`. All imports of `MsTeamSchema`, `MsChannelSchema`, `MsTeam`, and `MsChannel` in `channel.service.ts` and elsewhere are unaffected.

`MsEntitySchema` is intentionally not exported — it is an implementation detail. Only `MsTeamSchema` and `MsChannelSchema` are exported.

### Message length limits

Teams API documented limits:
- Channel messages: **28,000 characters**
- Chat messages: **4,000 characters**

These are character counts, not byte counts.

Add `.max()` to the `message` field in each send tool's input schema. The validation fires before any Graph API call, producing a clear Zod error.

### Redundant null-coalesce in `list-chats.tool.ts`

Current code (line 88–89):
```typescript
const effectiveLimit = input.limit ?? LIMIT;
const chats = await this.chatService.listChats(userProfileId, effectiveLimit);
```

`input.limit` has `.default(LIMIT)` in its Zod schema, so it is always a `number` by the time the handler runs — it can never be `undefined`. The `?? LIMIT` fallback is dead code and suggests to readers that a null case exists.

Fix: remove the `effectiveLimit` variable entirely and use `input.limit` directly:
```typescript
const chats = await this.chatService.listChats(userProfileId, input.limit);
```

Also remove the `const LIMIT = 50` constant from the file if it is only used for `effectiveLimit` and the default value. If it is used elsewhere, keep it — but the `?? LIMIT` expression in the handler must be removed regardless.

### Output symmetry for send tools

**`send_chat_message` current output:**
```typescript
const SendChatMessageOutputSchema = z.object({
  messageId: z.string(),
  chatId: z.string(),   // ← remove this
});

// in resolveAndSend:
return { messageId: result.id, chatId: chat.id };  // ← remove chatId
```

**`send_chat_message` target output:**
```typescript
const SendChatMessageOutputSchema = z.object({
  messageId: z.string(),
});

// in resolveAndSend:
return { messageId: result.id };
```

The `chatId` field is already known to the caller (they provided `chatIdentifier` which resolved to the chat). Removing it reduces response size.

**`send_channel_message` current output** is already `{ messageId: string, webUrl?: string }` — no change needed to the messageId field. The `webUrl` optional field is kept.

## Implementation

### `services/teams-mcp/src/chat/chat.dtos.ts`

Replace the two separate schema definitions with a shared base. The `MsEntitySchema` const is placed before both exports, at line 5 (before `MsTeamSchema`):

```typescript
const MsEntitySchema = z.object({
  id: z.string(),
  displayName: z.string(),
  description: z.string().optional(),
});

export const MsTeamSchema = MsEntitySchema;
export type MsTeam = z.infer<typeof MsTeamSchema>;

export const MsChannelSchema = MsEntitySchema;
export type MsChannel = z.infer<typeof MsChannelSchema>;
```

Remove the old separate `z.object({ ... })` definitions for both schemas.

### `services/teams-mcp/src/chat/tools/send-channel-message.tool.ts`

In `SendChannelMessageInputSchema`, update the `message` field:

```typescript
message: z.string().max(28_000).describe('Plain text message content to send'),
```

No changes to `SendChannelMessageOutputSchema` — it already returns `{ messageId: string, webUrl?: string }`.

### `services/teams-mcp/src/chat/tools/send-chat-message.tool.ts`

In `SendChatMessageInputSchema`, update the `message` field:

```typescript
message: z.string().max(4_000).describe('Plain text message content to send'),
```

Replace `SendChatMessageOutputSchema`:

```typescript
const SendChatMessageOutputSchema = z.object({
  messageId: z.string(),
});
```

Update the `resolveAndSend` return statement:

```typescript
return { messageId: result.id };
```

Update the return type annotation on `resolveAndSend`:

```typescript
private async resolveAndSend(
  userProfileId: string,
  chatIdentifier: string,
  message: string,
): Promise<z.output<typeof SendChatMessageOutputSchema>>
```

### `services/teams-mcp/src/chat/tools/list-chats.tool.ts`

Remove line 88 (`const effectiveLimit = input.limit ?? LIMIT;`).

Change line 89 from:
```typescript
const chats = await this.chatService.listChats(userProfileId, effectiveLimit);
```
to:
```typescript
const chats = await this.chatService.listChats(userProfileId, input.limit);
```

Change line 95 from:
```typescript
truncated: chats.length === effectiveLimit,
```
to:
```typescript
truncated: chats.length === input.limit,
```

Check whether `LIMIT` is used anywhere else in the file. If it is only referenced by the removed `effectiveLimit` assignment and possibly the `.default(LIMIT)` in the schema, keep it for the schema default. If it was only used in `effectiveLimit`, remove the `const LIMIT = 50` declaration too.

## Acceptance Criteria

- `chat.dtos.ts` contains a single `MsEntitySchema` definition; `MsTeamSchema` and `MsChannelSchema` are both assigned from it with no field duplication.
- `MsEntitySchema` is not exported from `chat.dtos.ts`.
- `z.infer<typeof MsTeamSchema>` and `z.infer<typeof MsChannelSchema>` both equal `{ id: string; displayName: string; description?: string }` — no downstream type errors.
- Submitting a `message` longer than 28,000 characters to `send_channel_message` returns a Zod validation error with no Graph API call made.
- Submitting a `message` longer than 4,000 characters to `send_chat_message` returns a Zod validation error with no Graph API call made.
- `send_chat_message` returns `{ messageId: string }` only — no `chatId` field in the response.
- `send_channel_message` returns `{ messageId: string }` and optionally `{ messageId: string, webUrl: string }` when `includeWebUrl: true` — unchanged from current.
- `list-chats.tool.ts` does not contain the expression `?? LIMIT` (or `?? 50`) in the handler method body.
- `list-chats.tool.ts` uses `input.limit` directly in the `listChats` call and the `truncated` expression.
- No runtime behaviour changes for callers other than the new validation tightening and the removal of `chatId` from `send_chat_message` output.
