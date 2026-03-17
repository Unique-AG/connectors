# Render `eventDetail` system messages as human-readable text

## Context

When `includeSystemMessages: true`, system messages currently show empty or meaningless content. Their payload is in the `eventDetail` field, not in `body.content`. The Graph API provides structured objects for about 15 event types, each discriminated by `@odata.type`. Without rendering them, enabling system messages adds noise rather than information.

After this ticket, system messages will render in the IRC transcript as:

```
── Alice Smith added Bob Jones, Carol White ──
── Alice Smith renamed the chat to 'Q4 Planning' ──
── Call ended (1m 30s) ──
```

Reference: https://learn.microsoft.com/en-us/graph/api/resources/chatmessageeventdetail

## Behaviour

### Graph API shape

`eventDetail` is returned as a nested object on system messages. Its `@odata.type` discriminator is always present. Example:

```json
{
  "messageType": "systemEventMessage",
  "eventDetail": {
    "@odata.type": "#microsoft.graph.membersAddedEventMessageDetail",
    "members": [
      { "id": "...", "displayName": "Bob Jones" },
      { "id": "...", "displayName": "Carol White" }
    ],
    "initiator": {
      "user": { "id": "...", "displayName": "Alice Smith" }
    }
  }
}
```

### Supported event types and rendering

| `@odata.type` | Relevant properties | Rendered as |
|---|---|---|
| `#microsoft.graph.callEndedEventMessageDetail` | `callDuration` (ISO 8601 duration, e.g. `"PT1M30S"`) | `"Call ended (1m 30s)"` |
| `#microsoft.graph.membersAddedEventMessageDetail` | `members[].displayName`, `initiator.user.displayName` | `"<initiator> added <name1>, <name2>"` |
| `#microsoft.graph.membersDeletedEventMessageDetail` | `members[].displayName`, `initiator.user.displayName` | `"<initiator> removed <name1>, <name2>"` |
| `#microsoft.graph.chatRenamedEventMessageDetail` | `chatDisplayName`, `initiator.user.displayName` | `"<initiator> renamed the chat to '<chatDisplayName>'"` |
| `#microsoft.graph.teamRenamedEventMessageDetail` | `teamDisplayName`, `initiator.user.displayName` | `"<initiator> renamed the team to '<teamDisplayName>'"` |
| all others | — | `"[system event]"` |

### Duration parsing

`callDuration` uses ISO 8601 duration format. Teams uses a limited subset: hours, minutes, and seconds only (e.g. `"PT1M30S"`, `"PT45S"`, `"PT2H"`, `"PT1H5M20S"`). No days or months appear in call durations.

Write a small helper `parseDuration(iso: string): string` using a regex. If a duration-parsing library is already present in the project's `package.json`, use it instead — check before writing the regex. Given Teams' limited format, a regex is acceptable:

```typescript
function parseDuration(iso: string): string {
  const match = iso.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!match) return iso; // fallback: return raw string
  const [, h, m, s] = match;
  const parts: string[] = [];
  if (h) parts.push(`${h}h`);
  if (m) parts.push(`${m}m`);
  if (s) parts.push(`${s}s`);
  return parts.join(' ') || iso;
}
```

Examples: `"PT1M30S"` → `"1m 30s"`, `"PT45S"` → `"45s"`, `"PT2H"` → `"2h"`, `"PT1H5M20S"` → `"1h 5m 20s"`.

### Conditional `$select`

`eventDetail` is only fetched when `includeSystemMessages: true`, to avoid wasting Graph API response bandwidth when the caller does not want system messages.

Pass a boolean flag to `ChatService.getChatMessages` to signal this:

```typescript
// in the service options object
includeEventDetail?: boolean;
```

When `includeEventDetail` is true, append `,eventDetail` to the `$select` string:

```typescript
const selectFields = 'id,createdDateTime,from,body,attachments,messageType';
const select = options.includeEventDetail
  ? `${selectFields},eventDetail`
  : selectFields;
```

The tool passes `includeEventDetail: input.includeSystemMessages` in the options object.

## Implementation

### `services/teams-mcp/src/chat/chat.dtos.ts`

Add `eventDetail` to `MsChatMessageSchema` before the `.transform()` call:

```typescript
eventDetail: z.record(z.unknown()).optional(),
```

Using `z.record(z.unknown())` rather than `z.unknown()` means the parsed value is typed as `Record<string, unknown>`, which gives access to `eventDetail['@odata.type']` and other fields without type casts in the rendering function.

Update the `.transform()` output to pass through `eventDetail`:

```typescript
.transform((msg) => ({
  id: msg.id,
  createdDateTime: msg.createdDateTime,
  messageType: msg.messageType,
  senderDisplayName: ...,
  content: msg.body.content,
  contentType: msg.body.contentType,
  attachments: ...,
  eventDetail: msg.eventDetail,   // ← add this line
}))
```

### `services/teams-mcp/src/chat/utils/normalize-content.ts`

Add and export `renderSystemMessage`:

```typescript
export function renderSystemMessage(eventDetail: Record<string, unknown> | undefined): string {
  if (!eventDetail) return '[system event]';

  const type = eventDetail['@odata.type'] as string | undefined;

  switch (type) {
    case '#microsoft.graph.callEndedEventMessageDetail': {
      const duration = eventDetail['callDuration'] as string | undefined;
      return duration ? `Call ended (${parseDuration(duration)})` : 'Call ended';
    }
    case '#microsoft.graph.membersAddedEventMessageDetail': {
      const initiator = (eventDetail['initiator'] as any)?.user?.displayName ?? 'Someone';
      const members = ((eventDetail['members'] as any[]) ?? [])
        .map((m) => m.displayName)
        .filter(Boolean)
        .join(', ');
      return `${initiator} added ${members || 'someone'}`;
    }
    case '#microsoft.graph.membersDeletedEventMessageDetail': {
      const initiator = (eventDetail['initiator'] as any)?.user?.displayName ?? 'Someone';
      const members = ((eventDetail['members'] as any[]) ?? [])
        .map((m) => m.displayName)
        .filter(Boolean)
        .join(', ');
      return `${initiator} removed ${members || 'someone'}`;
    }
    case '#microsoft.graph.chatRenamedEventMessageDetail': {
      const initiator = (eventDetail['initiator'] as any)?.user?.displayName ?? 'Someone';
      const name = (eventDetail['chatDisplayName'] as string | undefined) ?? '(unnamed)';
      return `${initiator} renamed the chat to '${name}'`;
    }
    case '#microsoft.graph.teamRenamedEventMessageDetail': {
      const initiator = (eventDetail['initiator'] as any)?.user?.displayName ?? 'Someone';
      const name = (eventDetail['teamDisplayName'] as string | undefined) ?? '(unnamed)';
      return `${initiator} renamed the team to '${name}'`;
    }
    default:
      return '[system event]';
  }
}
```

`parseDuration` is a module-private helper in the same file (not exported).

### `services/teams-mcp/src/chat/chat.service.ts`

Add `includeEventDetail?: boolean` to the `options` parameter of `getChatMessages` (alongside `pageToken`, `order`, `since`, `before` added in prior tickets).

Conditionally extend `$select`:

```typescript
const baseSelect = 'id,createdDateTime,from,body,attachments,messageType';
const select = options.includeEventDetail ? `${baseSelect},eventDetail` : baseSelect;
// use `select` in .select(...)
```

### `services/teams-mcp/src/chat/tools/get-chat-messages.tool.ts`

Pass `includeEventDetail` in the options object:

```typescript
const { messages, nextPageToken } = await this.chatService.getChatMessages(
  userProfileId,
  chat.id,
  input.limit,
  {
    pageToken: input.pageToken,
    order: input.order,
    since: input.since,
    before: input.before,
    includeEventDetail: input.includeSystemMessages,
  },
);
```

In `renderTranscript`, when rendering system messages, call `renderSystemMessage`:

```typescript
import { normalizeContent, renderSystemMessage } from '../utils/normalize-content';

// inside renderTranscript, for system messages:
} else if (input.includeSystemMessages) {
  const description = renderSystemMessage(m.eventDetail);
  lines.push(`── ${description} ──`);
}
```

## Acceptance Criteria

- `MsChatMessageSchema` in `chat.dtos.ts` includes `eventDetail: z.record(z.unknown()).optional()`.
- The `.transform()` output of `MsChatMessageSchema` includes `eventDetail` so it is accessible on the parsed `MsChatMessage` type.
- `eventDetail` is included in the Graph API `$select` only when `includeSystemMessages: true`; it is absent from `$select` when `includeSystemMessages: false`.
- `renderSystemMessage` is exported from `normalize-content.ts`.
- `renderSystemMessage` is covered by unit tests for all 5 handled event types:
  - `callEndedEventMessageDetail` with a `callDuration` value → `"Call ended (Xm Ys)"`
  - `membersAddedEventMessageDetail` → `"<initiator> added <names>"`
  - `membersDeletedEventMessageDetail` → `"<initiator> removed <names>"`
  - `chatRenamedEventMessageDetail` → `"<initiator> renamed the chat to '<name>'"`
  - `teamRenamedEventMessageDetail` → `"<initiator> renamed the team to '<name>'"`
  - unknown `@odata.type` → `"[system event]"` without throwing
  - `undefined` input → `"[system event]"` without throwing
- `parseDuration` correctly converts: `"PT1M30S"` → `"1m 30s"`, `"PT45S"` → `"45s"`, `"PT2H"` → `"2h"`, `"PT1H5M20S"` → `"1h 5m 20s"`.
- In the IRC transcript with `includeSystemMessages: true`, call ended renders as `── Call ended (Xm Ys) ──`.
- In the IRC transcript with `includeSystemMessages: true`, member-added events render as `── <initiator> added <names> ──`.
- With `includeSystemMessages: false`, system messages are excluded and `eventDetail` is not fetched.
