# Design: MS Graph folder/directory filtering for KQL email search

**Ticket:** UN-21097

## Problem

The MS Graph KQL search currently uses `/users/{mailbox}/messages` for every query, which searches the entire mailbox. Two gaps result:

1. No folder filtering — users cannot scope a KQL search to "Inbox" or a custom folder.
2. Delegated mailboxes with **directory-only** access (not full mailbox access) expose a curated list of accessible folder IDs. Sending a `/messages` request against those mailboxes is outside the granted permission scope. The correct approach is to expand each accessible folder into its own batch sub-request.

## Solution

### Overview

Add an optional `directories` field to `MsGraphKqlQuerySchema` alongside the existing `mailbox` and `kqlQuery`. The batch request builder selects the right Microsoft Graph endpoint per mailbox based on a four-case decision tree. Folder name/ID resolution (e.g. "Inbox" → provider folder ID) is extracted as a shared pure-function utility reused by both the MS Graph path and the existing semantic-search cleanup query.

The `translateQueriesToBatchRequests` logic is split into a dedicated `BuildMsGraphKqlBatchRequestsQuery` injectable, leaving `MsGraphKqlSearchEmailsQuery` responsible only for HTTP execution and result mapping.

Batch execution is rewritten as a two-round model: a primary round and a single retry round for transient failures, using a mutable queue with scoped drain-on-failure.

### Architecture

#### New files

**`resolve-directory-ids.util.ts`**
Pure function extracted from `CleanupSearchConditionsForUserQuery.sanitizeWrongDirectoryIds`. Signature:

```ts
resolveDirectoryIds(
  rawIds: string[],
  availableDirectories: Array<{ providerDirectoryId: string; displayName: string }>,
): { resolvedIds: string[]; unrecognized: string[] }
```

No DI. Importable by both `CleanupSearchConditionsForUserQuery` and `BuildMsGraphKqlBatchRequestsQuery`.

---

**`build-ms-graph-kql-batch-requests.query.ts`**
`@Injectable()` query. Injects `GetDelegatedAccessQuery` and `DRIZZLE`.

Translates `QueryInput[]` → `{ requests: GraphBatchRequest[]; skippedFolders: Array<{ mailbox: string; folder: string }> }`.

`GraphBatchRequest` gains an optional `folderId?: string`. When set, the URL becomes `/users/{mailbox}/mailFolders/{folderId}/messages`; when absent it remains `/users/{mailbox}/messages`.

**Four-case URL logic per (query, mailbox) pair:**

| Case | Condition | Endpoint |
|------|-----------|----------|
| 1 | Own mailbox, no `directories` | `/users/{mailbox}/messages` |
| 2 | Full delegated access, no `directories` | `/users/{mailbox}/messages` |
| 3 | Directory-only delegated access, no `directories` | One `/users/{mailbox}/mailFolders/{id}/messages` per accessible folder |
| 4 | Any mailbox, `directories` specified | One `/users/{mailbox}/mailFolders/{resolvedId}/messages` per resolved folder |

**Directory resolution per mailbox:**
- Own mailbox → query `directories WHERE userProfileId = userProfile.id AND ignoreForSync = false`
- Full delegated mailbox → query `directories WHERE userProfileId = ownerUserId AND ignoreForSync = false`
- Directory-only delegated mailbox → same DB query but intersect results with `msGraphDirectoryIds` from the delegated access record

Call `resolveDirectoryIds` with the input names/IDs and the fetched directory records. Unresolved names are collected into `skippedFolders`.

---

#### Modified files

**`ms-graph-kql-search-emails.query.ts`**

Remove `translateQueriesToBatchRequests`. Wire in `BuildMsGraphKqlBatchRequestsQuery`.

Replace `for (const batch of chunk(batchRequests, 20))` with a two-round execution model:

```
round1 = executeBatchRound(allRequests)
round2 = executeBatchRound(round1.retryRequests)   // called once, even if empty
hits   = [...round1.hits, ...round2.hits]
```

**`executeBatchRound`** private method signature:
```ts
executeBatchRound(requests: GraphBatchRequest[]): Promise<{
  hits: Hit[]
  retryRequests: GraphBatchRequest[]
  lostAccessMailboxes: Set<string>
  throttledMailboxes: Set<string>
}>
```

Internally uses a mutable queue (`queue = [...requests]`) and processes in chunks of 20.

**Queue drain rules on 403/404:**
- Request was for a **full-access** delegated mailbox → drain all remaining queue entries where `entry.mailbox === failedMailbox`; fire `markNoFullAccess`
- Request was for a **folder-level** (directory-only) access → drain only entries where `entry.mailbox === failedMailbox && entry.folderId === failedFolderId`; do NOT fire `markNoFullAccess`

**Retry candidates (go into `retryRequests`):**
- Status 429
- Status ≥ 500
- Entire `$batch` POST throws (network/timeout) → whole chunk becomes retry candidates

**Not retried:**
- 403/404 on delegated (permanent — drain queue)
- Schema validation failures

---

**`search-conditions.dto.ts`**

`MsGraphKqlQuerySchema` gains:
```ts
directories: z
  .array(z.string())
  .optional()
  .describe(
    'Folder names or IDs to restrict this query to. ' +
    'Pass well-known names directly: "Inbox", "Sent Items", "Drafts", "Archive", "Outbox". ' +
    'For custom folders pass the folder ID from `list_mailboxes_and_directories`. ' +
    'NEVER encode folder filtering inside the kqlQuery string — `folder:` is not a supported KQL property and is silently stripped. ' +
    'Use this field instead.',
  )
```

---

**`search-emails-tool.meta.ts`**

`META_MS_GRAPH` system prompt updated:
- Document the `directories` field and when to use it
- Explicitly state that `folder:` inside `kqlQuery` has no effect — use `directories` instead
- List accepted well-known folder names

---

**`cleanup-search-conditions-for-user.query.ts`**

Replace private `sanitizeWrongDirectoryIds` call with the shared `resolveDirectoryIds` utility. Behaviour is unchanged.

### Error Handling

**Search summary** is composed from three sources after both rounds complete:

| Source | Message |
|--------|---------|
| Throttled mailboxes (round 1 or 2) | `"Search was throttled for some mailboxes — results may be incomplete."` |
| Lost-access mailboxes | `"Could not access mailbox {X} — it was excluded from results."` |
| Skipped folders (from build query) | `"Folder '{name}' in mailbox {X} was not recognized and was excluded."` |

All non-empty parts are joined with newlines into the returned `searchSummary`.

### Testing Strategy

New cases in the existing `__tests/ms-graph-kql-search-emails.query.spec.ts`:

- Cases 1/2: no `directories`, own/full-delegated → URL uses `/messages`
- Case 3: directory-only mailbox, no `directories` → one sub-request per accessible folder
- Case 4: `directories` passed → resolves to folder IDs, uses `/mailFolders/{id}/messages`
- Unresolvable folder name → excluded from requests, appears in `searchSummary`
- 403 on full-access mailbox → entire mailbox drained from queue; later chunks don't contain it
- 403 on folder-level request → only that `mailbox+folderId` drained; sibling folders still sent
- 429 sub-response → goes into `retryRequests`, re-sent in round 2
- `resolveDirectoryIds` utility → unit-tested in isolation (pure function, no mocking needed)

## Out of Scope

- Pagination within a folder (currently unbounded by `$top`)
- Searching subfolders recursively
- Retrying more than once
- Supporting `directories` in the semantic (`SearchEmailsUnifiedInputSchema`) path — that already has `conditions.directories`

## Tasks

1. **Extract `resolveDirectoryIds` utility** — pull `sanitizeWrongDirectoryIds` out of `CleanupSearchConditionsForUserQuery` into `resolve-directory-ids.util.ts`; update the query to call it. Add isolated unit tests for the pure function.

2. **Create `BuildMsGraphKqlBatchRequestsQuery`** — implement the four-case URL logic with directory resolution (DB lookup per mailbox owner). Returns `{ requests, skippedFolders }`.

3. **Add `directories` to `MsGraphKqlQuerySchema`** — optional `z.array(z.string())` with the description above.

4. **Rewrite `MsGraphKqlSearchEmailsQuery`** — remove `translateQueriesToBatchRequests`, wire in the build query, replace `chunk` loop with `executeBatchRound` + one retry call, implement scoped queue drain (full-access vs folder-level), compose `searchSummary` from all three sources.

5. **Update `META_MS_GRAPH`** — document `directories`, instruct model not to use `folder:` in KQL.

6. **Tests** — cover all cases listed in the testing strategy above.
