# Cache team, channel, and chat list lookups

## Context

Every `send_channel_message` call makes two Graph API round-trips before sending: list all joined teams (to resolve the team name to an ID), then list all channels in that team (to resolve the channel name to an ID). Every `send_chat_message` and `get_chat_messages` call lists all chats to resolve the identifier. These are each full list fetches — potentially 50–200 items — performed synchronously on the hot path.

Teams, channels, and chat memberships change infrequently. A 5–15 minute TTL cache eliminates the latency overhead and Graph API quota consumption on repeated calls.

The project already uses `@nestjs/cache-manager` with `CACHE_MANAGER` in `UniqueUserMappingService`. The same pattern applies here: inject `Cache`, check on read, write on miss with a TTL.

`CacheModule` is registered at the app level in `AppModule` as `CacheModule.register({ isGlobal: true })` — it is globally available. No changes to `chat.module.ts` are needed.

## Behaviour

### Cache key design

Keys are scoped per `userProfileId` to prevent cross-user cache pollution:

| Data | Cache key pattern | TTL |
|------|-------------------|-----|
| Chat list | `chat-list:<userProfileId>` | 5 minutes (`300_000` ms) |
| Team list | `team-list:<userProfileId>` | 15 minutes (`900_000` ms) |
| Channel list | `channel-list:<userProfileId>:<teamId>` | 15 minutes (`900_000` ms) |

### What is cached vs. not cached

- `listChats` result: **cached** (5 min TTL)
- `listTeams` result: **cached** (15 min TTL)
- `listChannels` result: **cached per teamId** (15 min TTL)
- `getChatMessages` result: **never cached** — message content is time-sensitive and must always be fresh
- `sendChatMessage` / `sendChannelMessage` results: **never cached** — these are writes

### TTL note

`cache-manager` v5 uses milliseconds for TTL values (unlike v4 which used seconds). Use numeric literals with underscores for readability:

```typescript
const CHAT_LIST_TTL_MS = 300_000;   // 5 minutes
const LIST_TTL_MS = 900_000;        // 15 minutes
```

### Stale data behaviour

TTL-based expiry is sufficient. There is no active cache invalidation. If a channel is renamed within the TTL window, the cached name persists until the TTL expires and the next miss fetches fresh data. This is acceptable given the low rate of structural changes to teams/channels.

### Cache read/write pattern

Follow the exact pattern used in `UniqueUserMappingService`:

```typescript
const cacheKey = `chat-list:${userProfileId}`;
const cached = await this.cache.get<MsChat[]>(cacheKey);

if (cached) {
  return cached;
}

// ... fetch from Graph API ...

await this.cache.set(cacheKey, result, CHAT_LIST_TTL_MS);
return result;
```

Note: `UniqueUserMappingService` calls `this.cache.set(key, value)` with no TTL argument (indefinite cache), because Unique user IDs never change. The chat/team/channel lists use explicit TTL arguments.

## Implementation

### `services/teams-mcp/src/chat/chat.service.ts`

**Add imports** at the top of the file:

```typescript
import { Cache } from 'cache-manager';
import { Inject } from '@nestjs/common';
import { CACHE_MANAGER } from '@nestjs/cache-manager';
```

(`Injectable`, `Logger`, `NotFoundException` are already imported.)

**Add TTL constants** near the top of the file (outside the class):

```typescript
const CHAT_LIST_TTL_MS = 300_000; // 5 minutes
```

**Update constructor** to inject the cache:

```typescript
public constructor(
  private readonly graphClientFactory: GraphClientFactory,
  private readonly traceService: TraceService,
  @Inject(CACHE_MANAGER) private readonly cache: Cache,
) {}
```

**Wrap `listChats`** with cache logic. The method body becomes:

```typescript
const cacheKey = `chat-list:${userProfileId}`;
const cached = await this.cache.get<MsChat[]>(cacheKey);
if (cached) {
  span?.setAttribute('cache_hit', true);
  return cached;
}
span?.setAttribute('cache_hit', false);

// ... existing Graph API fetch ...

await this.cache.set(cacheKey, chats, CHAT_LIST_TTL_MS);
return chats;
```

`getChatMessages`, `resolveChatByNameOrMember`, and `sendChatMessage` are unchanged (no caching).

### `services/teams-mcp/src/chat/channel.service.ts`

**Add imports** at the top:

```typescript
import { Cache } from 'cache-manager';
import { Inject } from '@nestjs/common';
import { CACHE_MANAGER } from '@nestjs/cache-manager';
```

**Add TTL constant**:

```typescript
const LIST_TTL_MS = 900_000; // 15 minutes
```

**Update constructor**:

```typescript
public constructor(
  private readonly graphClientFactory: GraphClientFactory,
  private readonly traceService: TraceService,
  @Inject(CACHE_MANAGER) private readonly cache: Cache,
) {}
```

**Wrap `listTeams`**:

```typescript
const cacheKey = `team-list:${userProfileId}`;
const cached = await this.cache.get<MsTeam[]>(cacheKey);
if (cached) {
  span?.setAttribute('cache_hit', true);
  return cached;
}
span?.setAttribute('cache_hit', false);

// ... existing Graph API fetch ...

await this.cache.set(cacheKey, teams, LIST_TTL_MS);
return teams;
```

**Wrap `listChannels`**:

```typescript
const cacheKey = `channel-list:${userProfileId}:${teamId}`;
const cached = await this.cache.get<MsChannel[]>(cacheKey);
if (cached) {
  span?.setAttribute('cache_hit', true);
  return cached;
}
span?.setAttribute('cache_hit', false);

// ... existing Graph API fetch ...

await this.cache.set(cacheKey, channels, LIST_TTL_MS);
return channels;
```

`resolveTeamByName`, `resolveChannelByName`, and `sendChannelMessage` are unchanged (no caching).

### `services/teams-mcp/src/chat/chat.module.ts`

No changes required. `CacheModule` is registered globally in `AppModule` (`CacheModule.register({ isGlobal: true })`), so `CACHE_MANAGER` is injectable in any provider in the application without module-level imports.

## Acceptance Criteria

- `ChatService` constructor injects `@Inject(CACHE_MANAGER) private readonly cache: Cache`.
- `ChannelService` constructor injects `@Inject(CACHE_MANAGER) private readonly cache: Cache`.
- `listChats` returns the cached `MsChat[]` on the second call within 5 minutes without making a Graph API request.
- `listTeams` returns the cached `MsTeam[]` on the second call within 15 minutes without making a Graph API request.
- `listChannels` returns the cached `MsChannel[]` for the same `(userProfileId, teamId)` pair on the second call within 15 minutes.
- Cache keys for different `userProfileId` values are distinct — user A's chat list never satisfies user B's cache lookup.
- `channel-list` keys include the `teamId` — lists for different teams under the same user are stored separately.
- `getChatMessages` is never cached — each call fetches from the Graph API.
- `sendChatMessage` and `sendChannelMessage` are never cached.
- `chat.module.ts` is not modified — `CacheModule` global registration is noted as sufficient.
- TTL for chat list is `300_000` ms. TTL for team and channel lists is `900_000` ms.
- No `any` type casts in the cache get/set calls — use the generic `Cache.get<T>()` overload.
