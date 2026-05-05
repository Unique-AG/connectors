# Design: KQL search across delegated mailboxes

## Problem

`MsGraphKqlSearchEmailsQuery` only searched the signed-in user's own mailbox via `/search/query`. The semantic backend already supported cross-mailbox search through `hasFullDelegatedAccess=true` pipelines, but KQL was stuck on own-mailbox. This forced the LLM to use semantic search for any cross-mailbox lexical lookup — the wrong tool, since semantic search ranks by conceptual relevance, not exact keyword match. The DTO descriptions even hardcoded this limitation ("KQL search only filters the current user's own inbox"), pushing the LLM toward the wrong tool choice.

## Solution

### Overview

Replace the single `/search/query` call with a fan-out across the user's own mailbox plus every `hasFullDelegatedAccess=true` delegated mailbox the calling user has access to (ordered by `ownerEmail asc`, capped at 25 delegated + 1 own = 26 sub-requests per query). Each sub-request is a uniform `GET /users/{email}/messages?$search="<kql>"&$select=...&$top=...` with `Prefer: outlook.body-content-type="text"`, dispatched via Graph `$batch` in chunks of 20.

Failure handling is per-mailbox: a sub-request failure drops only that mailbox's results, never blocks the whole search. A `403 Forbidden` or `404 Not Found` on a delegated mailbox additionally flips `hasFullDelegatedAccess=false` for that pipeline (revoked access detected on use, self-healing).

The `mailbox` filter scopes the entire search to one mailbox: matches own → single own-mailbox sub-request; matches a `hasFullDelegatedAccess=true` pipeline → single delegated sub-request; matches neither → empty results with a `searchSummary` note, no API call.

Errors and notices surface through a `searchSummary: string | undefined` field alongside `results`, matching the pattern already used by `SemanticSearchEmailsQuery`. No synthetic `SearchEmailResult` entries are injected.

### Architecture

**`GetMailboxesWithFullDelegatedAccessQuery`** (new, `features/delegated-access/queries/`) — returns `string[]` of owner emails for which the calling user has `hasFullDelegatedAccess=true`. Filtered by `delegateUserId`, ordered by `userProfiles.email asc`, with an optional `mailbox` filter that returns 0 or 1 entries when set. Registered in `DelegatedAccessUtilsModule`.

**`MarkPipelineNoFullAccessCommand`** (new, `features/delegated-access/commands/`) — takes `{ delegateUserId, ownerEmail }`, looks up the owner's user profile, and sets `hasFullDelegatedAccess = false` on the matching pipeline. Idempotent (no-ops when the profile or pipeline is not found). Registered in `DelegatedAccessUtilsModule`.

**`TranslateGraphIdsToImmutableIdsQuery`** — extended with an optional `ownerEmail?: string` on its input object. When set, routes to `users/${ownerEmail}/translateExchangeIds`; otherwise falls back to `me/translateExchangeIds` (unchanged for existing callers). The entire method is now wrapped in a try/catch that returns an empty map on any failure.

**`MsGraphKqlSearchEmailsQuery`** (refactored) orchestrates:

1. Resolve the calling user's profile (email + id) via `GetUserProfileQuery`.
2. Fetch all `hasFullDelegatedAccess=true` mailboxes once via `GetMailboxesWithFullDelegatedAccessQuery`. For each input `{ kqlQuery, mailbox?, limit? }` resolve the target mailbox set:
   - `mailbox === ownEmail` → own only.
   - `mailbox` set, not own → look up in the delegated list; if not found, produce no sub-requests for this query (returns empty with `searchSummary` if all queries resolve to zero sub-requests).
   - `mailbox` unset → own + first 25 from the delegated list.
3. Build `GraphBatchRequest` objects (one per `(query, target mailbox)` pair) with TypeID-based `requestId`s. Dispatch via `$batch` in chunks of 20 using `client.api('$batch').post({ requests: [...] })`.
4. Per batch chunk: parse response with `batchResponseSchema`; on parse/network failure return `{ success: false, searchSummary: 'KQL search is currently unavailable...' }`.
5. Per sub-response: match back to the originating request via `requestId`; `403`/`404` on a delegated mailbox → add to `mailboxesWhichLostAccess` + fire `MarkPipelineNoFullAccessCommand` unawaited; other non-2xx → skip; `2xx` → parse body with `messageSchema` and collect hits.
6. Filter out any hits from `mailboxesWhichLostAccess`, then group by mailbox for round-robin interleaving (`mergeResults`), capped at `MAX_OUTPUT_RESULTS = 100`.
7. Group hits by source mailbox, fire per-mailbox `TranslateGraphIdsToImmutableIdsQuery` calls sequentially, fall back to `restId` per-hit on translate failure.
8. Map each hit to `SearchEmailResult`: `outlookWebLink` is `''` for delegated sources, `text` prefers `uniqueBody.content` falling back to `bodyPreview`.

**`SearchEmailsQuery`** — updated to thread `searchSummary` from both backends through to the caller. `run()` now returns `{ results: SearchEmailResult[], searchSummary: string | undefined }`.

**DTO and tool-meta updates** in `search-conditions.dto.ts` and `search-emails-tool.meta.ts` — all "KQL only searches the current user's own inbox" / "KQL does not support delegated access" claims removed.

### Error Handling

- **Per-sub-request isolation.** Each batch sub-response parsed independently; one failure never short-circuits others.
- **403 / 404 on a delegated mailbox.** Drop hits for that mailbox; fire `MarkPipelineNoFullAccessCommand` unawaited (self-healing for next search).
- **Transient failures (`429`, `5xx`, malformed sub-response).** Drop hits; leave the `hasFullDelegatedAccess` flag intact. No retry.
- **Top-level `$batch` POST failure.** Return `{ results: [], searchSummary: 'KQL search is currently unavailable; results were not returned.' }`. No throw.
- **Translate-ID failure (per mailbox).** Fall back to `restId` for that mailbox's hits; results still returned. Translation is enrichment, not gate-keeping.
- **`mailbox` filter unrecognized** (not own, not in `hasFullDelegatedAccess=true` set). Zero sub-requests produced for that query entry; if all entries resolve to zero sub-requests, return `{ results: [], searchSummary: 'In order to get results we need at least 1 query to execute' }`.
- **Flag-flip write failure.** Caught and ignored; next search retries the same mailbox, hits 403/404 again, and retries the flip.

### Key Implementation Notes

- **`mergeResults` uses `Array.from(indicesMap)` not `Object.entries(indicesMap)`** — `indicesMap` is a `Map`, and `Object.entries` on a Map always returns `[]`. Using `Array.from` snapshots the entries for each round-robin pass while allowing safe in-loop Map mutations.
- **`$batch` body format**: `{ requests: [...] }` (not a bare array) — Graph's batch endpoint requires the `requests` key.
- **Cap is 25 delegated** (not 39 as originally designed): fits in two batch calls of 20+6 = 26 sub-requests per input query.
- **No synthetic `SearchEmailResult` entries** for errors or notices — `searchSummary` is used instead, consistent with the semantic backend.

### Testing

20 behavioral tests on `MsGraphKqlSearchEmailsQuery` using mocked `GraphClientFactory` and mocked DB queries. Coverage:

- `mailbox` filter → own / delegated / unrecognized.
- `mailbox` unset → fan-out with 25-delegate cap (asserts total sub-request count across all batch calls).
- 403 and 404 on delegated → hits dropped + `MarkPipelineNoFullAccessCommand` fired.
- 403 on own mailbox → hits skipped, flag NOT flipped.
- Non-2xx (500) sub-response → skipped without error, `searchSummary` stays `undefined`.
- Top-level batch failure → `searchSummary` set, no throw.
- Round-robin merge across mailboxes.
- Results capped at 100.
- Dedup by `restId` across mailboxes.
- ID translation: immutable ID used when available; `restId` fallback when map is empty.
- `outlookWebLink` is the web link for own-mailbox results and `''` for delegated.
- `text` prefers `uniqueBody.content`, falls back to `bodyPreview`.

`GetMailboxesWithFullDelegatedAccessQuery` and `MarkPipelineNoFullAccessCommand` are not tested — they are pure DB code with no behavioral logic.

## Out of Scope

- Multi-batch retries / exponential backoff for transient failures.
- Surfacing per-mailbox transient failures to the LLM as warnings.
- Caching the searchable-mailboxes list across requests within a session.
- Pagination beyond `$top` per sub-request.
- Any UI for the user to discover that a pipeline lost full access (DB flag is the only signal; the next sync will reconcile).
- Cap-hint synthetic note when the user has more than 25 delegated mailboxes (dropped from original design — `searchSummary` is sufficient if needed in the future).
- Rebalancing the cap based on mailbox activity / recency. Alphabetical-by-owner-email.
- Touching the semantic backend's relevance ranking or the `mergeResults` logic in `SearchEmailsQuery`.
- Updating `packages/unique-api/src/content/search-content.dto.ts` (public Unique-API semantic search DTO, no KQL text).
