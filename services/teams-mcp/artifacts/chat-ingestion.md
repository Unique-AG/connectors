# Teams Chat & Channel Ingestion into Unique KB

## Context

PR #344 (`feat/teams-mcp-chat-messaging`) adds 6 MCP tools for reading/sending Teams messages, but everything is on-demand — nothing is persisted to the Unique knowledge base. This document describes the sync pipeline that ingests chat and channel thread history as structured text documents, enabling RAG search over Teams conversations.

---

## Document Model

| Content | Key | Document covers | Related |
|---|---|---|---|
| 1:1 chat | `teams:{tenantId}/chats/{otherPersonName\|chatId}` | Entire conversation history | Attachments (Phase 2) |
| Group chat | `teams:{tenantId}/chats/{topic\|chatId}` | Entire conversation history | Attachments (Phase 2) |
| Meeting chat | `teams:{tenantId}/chats/{meetingName\|chatId}` | Entire conversation history | Attachments (Phase 2) |
| Channel thread | `teams:{tenantId}/channels/{channelName\|channelId}/{threadRootId}` | Thread root + all replies | Attachments (Phase 2) |

**Name derivation (with ID fallback):**
- 1:1 → other member's `displayName` ?? `chatId`
- group/meeting → `topic` ?? `chatId`
- channel → `displayName` ?? `channelId`

**Timestamps:** full ISO 8601 UTC — Graph always returns UTC, no timezone ambiguity needed.

**Attachments Phase 1:** referenced inline as `[attachment: filename]`, not downloaded/ingested. Text extraction is Phase 2.

---

## Document Format

### Chat (1:1 / group / meeting)

```
Chat: Alice Smith (oneOnOne)
Members: you@company.com, alice@company.com
Started: 2026-03-10T14:22:00Z

---

[2026-03-10T14:22:00Z] You: Hey Alice, can you review the PR today?
[2026-03-10T14:24:00Z] Alice Smith: Sure, which one?
[2026-03-10T14:25:00Z] You: #344 – teams chat ingestion
[2026-03-10T14:27:00Z] Alice Smith: On it 👍
[2026-03-10T14:31:00Z] Alice Smith: [attachment: design-doc.pdf]
[2026-03-11T09:05:00Z] Alice Smith: Reviewed – left comments.
[2026-03-11T09:07:00Z] You: Good catch, will fix
```

### Channel Thread

```
Channel: #general | Team: Engineering
Thread started by: Alice Smith
Date: 2026-03-15T10:00:00Z

---

[2026-03-15T10:00:00Z] Alice Smith: Let's plan sprint 42. [attachment: sprint-42-scope.docx]
[2026-03-15T10:04:00Z] Bob Jones: I'll take the auth module
[2026-03-15T10:05:00Z] Alice Smith: @Bob sounds good
[2026-03-15T10:09:00Z] Charlie Dev: Can we move the deadline to Thursday?
[2026-03-15T10:11:00Z] Alice Smith: @Charlie yes, confirmed
```

Messages sorted **oldest-first** (`createdDateTime asc`). System messages (`messageType !== 'message'`) filtered out. Content normalized via existing `normalizeContent()` from `chat/utils/normalize-content.ts`.

---

## Sync Architecture

Teams-MCP uses **AMQP event-driven** processing (no `@nestjs/schedule` cron). Chat sync follows the same pattern used for transcript ingestion.

```
User → sync_chats_to_kb tool
         ↓ enqueue AMQP message
         unique.teams-mcp.chat.sync.requested { userProfileId }
         ↓
ChatSyncHandler.onSyncRequested()
         ↓
ChatSyncService.syncUser(userProfileId)
  ├── List all chats (GET /me/chats)
  │   └── For each chat → syncChat()
  │         ├── Check chat_sync_state: lastMessageAt unchanged? → skip
  │         ├── getAllChatMessages() [paginated, all pages]
  │         ├── formatChatDocument()
  │         └── UniqueChatService.ingestDocument() [3-stage]
  │
  └── List all teams + channels (existing ChannelService)
      └── For each channel → syncChannelThreads()
            ├── getChannelThreads() [all top-level messages]
            └── For each thread → syncThread()
                  ├── Check chat_sync_state: lastMessageAt unchanged? → skip
                  ├── getThreadReplies()
                  ├── formatChannelThreadDocument()
                  └── UniqueChatService.ingestDocument() [3-stage]

User → get_chat_sync_status tool → reads chat_sync_state table
```

**Diff strategy:** store `lastMessageAt` (ISO timestamp of newest message) per resource in `chat_sync_state`. On sync: fetch newest 1 message, compare with stored — if same, skip. If different, re-fetch all messages and re-upload the full document. The Unique `upsertContent` is idempotent by key, so re-uploads are safe.

**Concurrency:** `pLimit(3)` across chats/threads (configurable).

---

## Scope Structure in Unique

Follows the transcript scope pattern. `rootScopeId` is already configured in `unique.rootScopeId`.

```
rootScopeId
├── Teams Chats
│   ├── Alice Smith         ← scope per 1:1 chat
│   ├── Project Alpha       ← scope per group chat (by topic)
│   └── {chatId}            ← fallback when no name
└── Teams Channels
    └── Engineering         ← scope per team
        ├── general         ← scope per channel
        │   └── {threadId}  ← scope per thread (optional, or flat under channel)
        └── random
```

Access: syncing user gets read+write. Other chat participants — Phase 2 (requires resolving their Unique accounts via `UniqueUserService.findUserByEmail()`).

---

## New Files

### `src/drizzle/schema/chat-sync-state.table.ts`

```typescript
export const chatSyncResourceType = pgEnum('chat_sync_resource_type', ['chat', 'channel_thread']);
export const chatSyncStatus = pgEnum('chat_sync_status', ['pending', 'syncing', 'synced', 'failed']);

export const chatSyncState = pgTable(
  'chat_sync_state',
  {
    id: varchar().primaryKey().$default(() => typeid('chat_sync').toString()),
    userProfileId: varchar().notNull().references(() => userProfiles.id, { onDelete: 'cascade' }),
    resourceType: chatSyncResourceType().notNull(),
    resourceId: varchar().notNull(),      // chatId  OR  `teamId:channelId:threadId`
    resourceName: varchar(),              // resolved display name (for the document key)
    lastMessageAt: varchar(),             // ISO string of newest known message (diff key)
    lastSyncedAt: timestamp(),
    syncStatus: chatSyncStatus().notNull().default('pending'),
    errorMessage: text(),
    messageCount: integer().default(0),
    ...timestamps,
  },
  (t) => [unique().on(t.userProfileId, t.resourceType, t.resourceId)]
);
```

Export from `src/drizzle/schema/index.ts`. Run `pnpm drizzle-kit generate` after adding.

---

### `src/chat/utils/chat-formatter.ts`

Pure utility, no side effects. Reuses `normalizeContent()`.

```typescript
export function deriveChatName(chat: MsChat): string
// 1:1 → other member displayName ?? chatId
// group/meeting → topic ?? chatId

export function deriveChannelName(channel: MsChannel): string
// displayName ?? channelId

export function formatChatDocument(chat: MsChat, messages: MsChatMessage[]): string
// Header block + chronological IRC log lines
// Filters: messageType !== 'message' → skip
// Content: normalizeContent(body.content, body.contentType, attachments)

export function formatChannelThreadDocument(
  team: MsTeam,
  channel: MsChannel,
  rootMessage: MsChatMessage,
  replies: MsChatMessage[],
): string
// Header block + root + replies as IRC log lines
```

---

### `src/chat/chat-sync.service.ts`

```typescript
@Injectable()
export class ChatSyncService {
  constructor(
    private readonly chatService: ChatService,
    private readonly channelService: ChannelService,
    private readonly uniqueChatService: UniqueChatService,
    @InjectDrizzle() private readonly db: DrizzleDb,
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
  ) {}

  async syncUser(userProfileId: string): Promise<void>
  async getSyncStatus(userProfileId: string): Promise<ChatSyncStatusSummary>

  private async syncChat(userProfileId: string, chat: MsChat): Promise<void>
  private async syncChannelThread(
    userProfileId: string,
    team: MsTeam,
    channel: MsChannel,
    rootMessage: MsChatMessage,
  ): Promise<void>
}
```

---

### `src/unique/unique-chat.service.ts`

Follows `unique.service.ts` (transcript ingestion) pattern.

```typescript
@Injectable()
export class UniqueChatService {
  constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly contentService: UniqueContentService,
    private readonly scopeService: UniqueScopeService,
    private readonly userService: UniqueUserService,
    private readonly trace: TraceService,
  ) {}

  async ingestDocument(params: {
    ownerEmail: string;         // for scope access
    key: string;                // full document key
    title: string;
    content: string;            // formatted text/plain
    scopeRelativePath: string;  // e.g. "Teams Chats/Alice Smith"
    metadata: Record<string, string>;
  }): Promise<void>
  // → createScope(rootScopeId, scopeRelativePath)
  // → addScopeAccesses([owner read+write])
  // → upsertContent (register → get writeUrl/readUrl)
  // → uploadToStorage (PUT text/plain)
  // → upsertContent with fileUrl (finalize)
}
```

---

### `src/chat/amqp/chat-sync.handler.ts`

```typescript
@Injectable()
export class ChatSyncHandler {
  @RabbitSubscribe({
    exchange: MAIN_EXCHANGE.name,
    routingKey: 'unique.teams-mcp.chat.sync.requested',
    queue: 'unique.teams-mcp.chat.sync',
    queueOptions: { durable: true },
  })
  async onSyncRequested(msg: { userProfileId: string }): Promise<void>
}
```

---

### `src/chat/tools/sync-chats-to-kb.tool.ts`

- Parameters: none
- Action: enqueue AMQP message, update all `chatSyncState` rows for user to `pending`
- Returns: `{ status: 'queued', message: '...' }`
- Hints: `readOnlyHint: false`, `idempotentHint: false`

---

### `src/chat/tools/get-chat-sync-status.tool.ts`

- Parameters: none
- Action: query `chat_sync_state` for current user
- Returns:
  ```typescript
  {
    totalResources: number,
    synced: number,
    pending: number,
    syncing: number,
    failed: number,
    lastSyncedAt: string | null,
    resources: Array<{
      type: 'chat' | 'channel_thread',
      name: string,
      status: string,
      messageCount: number,
      lastMessageAt: string | null,
      lastSyncedAt: string | null,
      error?: string,
    }>
  }
  ```
- Hints: `readOnlyHint: true`

---

## Modified Files

### `src/chat/chat.service.ts`

Add three methods:

```typescript
// Paginated — fetches ALL pages oldest-first
public async getAllChatMessages(
  userProfileId: string,
  chatId: string,
): Promise<MsChatMessage[]>

// All top-level messages in a channel (each is a thread root)
public async getChannelThreads(
  userProfileId: string,
  teamId: string,
  channelId: string,
): Promise<MsChatMessage[]>

// All replies to a specific thread
public async getThreadReplies(
  userProfileId: string,
  teamId: string,
  channelId: string,
  threadId: string,
): Promise<MsChatMessage[]>
```

**Pagination pattern** (`getAllChatMessages`):
```typescript
const messages: MsChatMessage[] = [];
const client = this.graphClientFactory.createClientForUser(userProfileId);
let response = await client
  .api(`/chats/${chatId}/messages`)
  .top(50)
  .orderby('createdDateTime asc')
  .select('id,createdDateTime,from,body,attachments,messageType')
  .get();
while (response) {
  messages.push(...z.array(MsChatMessageSchema).parse(response.value));
  if (response['@odata.nextLink']) {
    response = await client.api(response['@odata.nextLink']).get();
  } else {
    break;
  }
}
return messages;
```

Graph endpoints used:
- `GET /chats/{chatId}/messages` — existing endpoint, add pagination + `messageType` field
- `GET /teams/{teamId}/channels/{channelId}/messages` — new
- `GET /teams/{teamId}/channels/{channelId}/messages/{messageId}/replies` — new

### `src/chat/chat.module.ts`

Add to providers:
- `ChatSyncService`
- `UniqueChatService`
- `ChatSyncHandler`
- `SyncChatsTool`
- `GetChatSyncStatusTool`

Add to imports: `UniqueModule` (if not already imported via global — check transcript module).

### `src/drizzle/schema/index.ts`

Export `chatSyncState`, `chatSyncResourceType`, `chatSyncStatus`.

---

## Graph API Permissions Required

All required OAuth scopes are present in `microsoft.provider.ts`:
- `Chat.Read` — read chat messages
- `Team.ReadBasic.All` — list joined teams
- `Channel.ReadBasic.All` — list channels
- `ChannelMessage.Read.All` — read channel messages and replies (delegated, required for `GET /teams/{id}/channels/{id}/messages`)
- `ChannelMessage.Send` — send channel messages
- `ChatMessage.Send` — send chat messages

Note: `Channel.ReadBasic.All` only covers listing channels, not reading their messages. `ChannelMessage.Read.All` is the correct scope for reading channel message content.

---

## Verification

1. **Unit tests** for `chat-formatter.ts`:
   - IRC log output format
   - Name derivation: 1:1 uses other member, group uses topic, fallback to ID
   - System message filtering (`chatEvent`, `systemEventMessage`)
   - `normalizeContent` integration (mentions, attachments inline)

2. **Manual E2E test:**
   - Call `sync_chats_to_kb` → returns `{ status: 'queued' }`
   - Poll `get_chat_sync_status` → watch `syncing` → `synced`
   - Verify `chat_sync_state` rows in DB (psql or Drizzle studio)
   - Search Unique KB for a keyword known to be in a chat message

3. **Edge cases:**
   - Chat with 0 messages → skip, mark `synced`, `messageCount: 0`
   - Chat with > 50 messages → pagination traverses all pages
   - Re-sync unchanged chat → `lastMessageAt` unchanged → skip (no re-upload)
   - Re-sync updated chat → full re-upload (upsert idempotent by key)
   - Channel thread with no replies → single-message document
   - Chat with null topic + null member displayName → falls back to chatId in key

---

## Out of Scope (Phase 2)

- **Attachment ingestion** — download + text extraction from PDF/DOCX/XLSX; upload as separate KB documents
- **Participant access control** — resolve other chat members' Unique accounts and grant scope read access
- **Scheduled sync** — cron-based background sync per user (requires `@nestjs/schedule`)
- **Webhook real-time sync** — new message → re-upload document immediately
- **`search_chat_history` tool** — thin wrapper over `UniqueContentService.search()` scoped to chat documents
- **Selective sync** — user specifies which chats/channels to include/exclude
