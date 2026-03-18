# Design: Create Draft Email — Attachment IDs from Knowledge Base

## Problem

`create-draft-email` in `outlook-semantic-mcp` currently accepts attachments as base64-encoded blobs passed directly by the caller. This is impractical for large files and does not integrate with the Unique knowledge base. Users should be able to reference files already stored in the knowledge base by their content ID, and the tool should handle the download and attachment transparently.

## Solution

### Overview

Replace the `attachments` (base64) input field with `attachmentIds: string[]` — a list of Unique content IDs (e.g., `cont_j23i0ifr44sdn7cz97ubleb7`). After creating the draft, the command iterates over each ID sequentially: downloads the file from the ingestion service via `GET /v1/content/{id}/file` using the service account, converts the buffer to base64, and uploads it to the draft via `POST /me/messages/{draftId}/attachments`. Each buffer is eligible for GC immediately after upload. Failures are collected and returned alongside the draft info — the draft is always created.

The download capability is added to the `unique-api` package so any connector can reuse it.

### Architecture

**Files changed:**

| File | Change |
|---|---|
| `packages/unique-api/src/content/unique-content.facade.ts` | Add `downloadContentById` to interface |
| `packages/unique-api/src/content/content.service.ts` | Implement `downloadContentById` |
| `packages/unique-api/src/content/content.dto.ts` | Add `DownloadedContent` return type |
| `services/outlook-semantic-mcp/src/features/email-management/email-management.module.ts` | Import `UniqueApiFeatureModule` |
| `services/outlook-semantic-mcp/src/features/email-management/create-draft-email.command.ts` | Replace `attachments` with `attachmentIds`, inject `UniqueApiClient`, add sequential download+upload loop |
| `services/outlook-semantic-mcp/src/features/email-management/create-draft-email.tool.ts` | Replace `attachments` schema with `attachmentIds`, update output schema |
| `services/outlook-semantic-mcp/src/features/email-management/create-draft-email-tool.meta.ts` | Update system prompt to describe content IDs |

**Data flow:**

```
Tool receives: { attachmentIds: ['cont_j23i0ifr44sdn7cz97ubleb7', ...], ... }
  │
  ├─ Command: POST /me/messages → draftId
  │
  ├─ for each attachmentId (sequentially):
  │    1. uniqueApi.content.downloadContentById(id)   // GET /v1/content/{id}/file → Buffer
  │    2. base64 encode + POST /me/messages/{draftId}/attachments
  │    3. Buffer goes out of scope → GC eligible
  │    4. on any error: collect { contentId, reason }, continue
  │
  └─ Return { success: true, draftId, attachmentsFailed: [{ contentId, reason }] }
```

**`downloadContentById` in `unique-api`:**
- Calls `GET /v1/content/{id}/file` via `UniqueHttpClient` using the existing ingestion service base URL
- Returns `{ data: Buffer; filename: string; mimeType: string }`
- Extracts `filename` from `Content-Disposition` response header (fallback: `contentId`)
- Extracts `mimeType` from `Content-Type` response header (fallback: `application/octet-stream`)

**Zod schema (`attachmentIds`):**
```
attachmentIds: z.array(z.string()).optional().describe(
  'IDs of files from the Unique knowledge base to attach to this email. ' +
  'These are content IDs, not file paths. ' +
  'Examples: cont_j23i0ifr44sdn7cz97ubleb7, cont_h346inqws1s3686luftk96yt, cont_tl4uzdijj93r98lcxtk8js9k'
)
```

### Error Handling

| Failure point | Behavior |
|---|---|
| Draft creation fails | Throw `InternalServerErrorException` — same as today |
| `downloadContentById` fails (404, 403, network) | Collect `{ contentId, reason }`, continue to next |
| Attachment upload to MS Graph fails | Collect `{ contentId, reason }`, continue to next |
| All attachments fail | Draft still returned; `attachmentsFailed` lists all IDs |
| No `attachmentIds` provided | Skip loop entirely — behaves exactly as today |

`attachmentsFailed` is omitted from the response when empty.

**MS Graph 25 MB limit:** No special handling — MS Graph returns an error which is caught and collected in `attachmentsFailed`.

### Testing Strategy

No new tests. The command logic requires heavy mocking of both the Graph client and UniqueApiClient, adding little confidence. Exception: any pure utility function extracted for filename/MIME parsing from headers is worth a unit test.

## Out of Scope

- Files larger than 25 MB (MS Graph rejects naturally)
- Preview PDF variants of content
- Item attachments (forwarded emails as attachments)
- Retry logic on failed downloads or uploads
- Keeping the old base64 `attachments` field alongside `attachmentIds`

## Tasks

1. **Add `downloadContentById` to `unique-api`** — Add method to `UniqueContentFacade` interface and implement in `ContentService`. It calls `GET /v1/content/{id}/file`, buffers the binary response, and extracts filename and MIME type from response headers with sensible fallbacks. Add `DownloadedContent` return type to `content.dto.ts`.

2. **Wire `UniqueApiFeatureModule` into `EmailManagementModule`** — Import `UniqueApiFeatureModule` in `email-management.module.ts` so `UniqueApiClient` is injectable into `CreateDraftEmailCommand`.

3. **Update `CreateDraftEmailCommand`** — Replace `attachments` (base64 array) with `attachmentIds: string[]`. Inject `UniqueApiClient`. After draft creation, loop sequentially: download → base64 encode → upload to `/me/messages/{draftId}/attachments`, collecting any failures. Update `CreateDraftEmailResult` type to include `attachmentsFailed`.

4. **Update `CreateDraftEmailTool` schema and output** — Replace the `attachments` Zod field with `attachmentIds: z.array(z.string()).optional()` with description including example IDs. Update output schema to include `attachmentsFailed`. Update `CreateDraftEmailInput` interface to match.

5. **Update system prompt and schema descriptions** — In `create-draft-email-tool.meta.ts`, replace base64 attachment guidance with content ID guidance, including example IDs and explanation that the tool resolves them automatically.
