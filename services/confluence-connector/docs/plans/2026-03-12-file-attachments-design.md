# Design: File Attachment Ingestion

## Problem

The confluence-connector v2 currently ingests page and blog post content but does not support file attachments. Users who attach PDFs, documents, images, and other files to Confluence pages cannot have those files indexed and available in Unique. V1 had a limited approach (parsing hrefs from HTML body), and we want a proper native Confluence Attachment API integration.

## Solution

### Overview

Add native Confluence Attachment API support to the v2 connector by leveraging the `children.attachment` expand parameter on existing API calls — no separate attachment API requests needed. Attachment metadata (id, title, mediaType, fileSize, download URL, version timestamp) comes inline with page responses. Attachments participate in the same diff mechanism as pages — tracked by `version.when` — so only new or updated attachments are re-ingested on subsequent sync cycles. Binary content is streamed directly from Confluence to the Unique write service (no intermediate disk storage), following the SharePoint connector pattern.

Key insight: adding/removing/updating an attachment in Confluence updates the parent page's `version.when`, so the existing page diff naturally detects attachment changes.

The feature is per-tenant configurable with:
- `attachments.enabled` (boolean, default: `false`)
- `attachments.allowedExtensions` (string array, e.g., `["pdf", "docx", "xlsx"]`)
- `attachments.maxFileSizeBytes` (number, default from app-level `MAX_FILE_SIZE_BYTES`)

### Architecture

#### 1. Attachment Discovery (via expand on existing API calls)

Instead of making separate API calls per page, we add `children.attachment,children.attachment.version,children.attachment.extensions` to the `expand` parameter on all existing API calls when `attachments.enabled` is true:

- **`searchPagesByLabel`** (discovery phase):
  - Cloud: `expand=metadata.labels,version,space,children.attachment,children.attachment.version,children.attachment.extensions`
  - DC: same expand, added to existing query
- **`getDescendantPages`** (discovery phase): same expand additions
- **`getPageById`** (content fetch phase):
  - Cloud: `expand=body.storage,version,space,metadata.labels,children.attachment,children.attachment.version,children.attachment.extensions`
  - DC: same expand additions

Each page response includes `children.attachment.results[]` with up to 25 attachments. For pages with >25 attachments, follow `children.attachment._links.next` for pagination (rare edge case).

Each attachment provides:
- `id` (e.g., `"att23953409"`)
- `title` (filename, e.g., `"report.pdf"`)
- `version.when` (ISO timestamp for diffing)
- `extensions.mediaType` (e.g., `"application/pdf"`)
- `extensions.fileSize` (bytes, used for Content-Length header)
- `_links.download` (relative download path)

Filter out attachments that:
- Have extensions not in `allowedExtensions`
- Exceed `maxFileSizeBytes`

#### 2. Attachment Diffing

Attachment keys (`{tenantName}/spaceId_spaceKey/pageId/attachmentId`) are fed into the existing `FileDiffService` alongside page keys. The diff is performed per-space using `partialKey` — both page and attachment keys share the same `{tenantName}/{spaceId}_{spaceKey}` prefix, so the diff API correctly tracks both in one call.

Each attachment becomes a `FileDiffItem`:
```
{ key: "pageId/attachmentId", url: attachmentWebUrl, updatedAt: attachment.version.when }
```

The diff returns new/updated/deleted for both pages and attachments. No structural changes needed to `FileDiffService` — just include attachment items in the input array.

#### 3. Attachment Content Streaming

New method on `IngestionService` — `ingestAttachment(attachment, scopeId)`:
1. **Register** content with Unique API (mimeType from `extensions.mediaType`, byteSize from `extensions.fileSize`)
2. **Download stream** from Confluence using the attachment's `_links.download` path (authenticated request, returns binary stream)
3. **Convert** to Node.js `Readable` via `Readable.fromWeb()` (SharePoint connector pattern)
4. **PUT stream** directly to writeUrl (undici with `body: stream`, Content-Length from `extensions.fileSize`, `x-ms-blob-type: BlockBlob`)
5. **Finalize** ingestion with readUrl

On failure: rollback by deleting the registered content (same as SharePoint connector).

#### 4. API Client Extension

Add to both `CloudConfluenceApiClient` and `DataCenterConfluenceApiClient`:
- `getAttachmentDownloadStream(downloadPath: string): Promise<Readable>` — downloads binary content as a Node.js Readable stream via authenticated request

The expand parameter additions for attachment discovery are conditional — only appended when `attachments.enabled` is true in tenant config.

For pages with >25 attachments, add a `fetchRemainingAttachments(nextUrl: string)` method to paginate through `children.attachment._links.next`.

#### 5. Orchestration

Updated sync flow in `ConfluenceSynchronizationService`:
```
discoverPages()  // now includes attachment metadata via expand
  → computeDiff(pages + attachments)  // attachment keys included in diff
  → fetchAndIngestPages()  // getPageById also includes attachment details
    → for each page: ingestPage() + ingestAttachments()
  → deleteRemovedContent  // handles both pages and attachments from diff
```

#### 6. Configuration

New config section in tenant YAML under `ingestion`:
```yaml
ingestion:
  attachments:
    enabled: false
    allowedExtensions:
      - pdf
      - docx
      - xlsx
      - pptx
      - txt
      - csv
    maxFileSizeBytes: 209715200  # 200MB default
```

New Zod schema for attachment config fields. Added to the existing ingestion schema and tenant config validation.

### Error Handling

- **Download stream failure**: Log error, clean up registered content (delete via Unique API, same pattern as SharePoint connector), continue with next attachment.
- **Upload failure (PUT to writeUrl)**: Same as download — rollback registration, log, continue.
- **Size exceeded at runtime**: If actual download exceeds `maxFileSizeBytes`, abort stream and rollback.
- **Rate limiting**: Attachment downloads go through existing `RateLimitedHttpClient`, respecting `apiRateLimitPerMinute`.
- **Deleted page cascade**: When a page is deleted, its attachment keys (under `pageId/`) are included in deletion diff automatically (they weren't submitted, so the diff marks them deleted).
- **Attachment pagination failure**: Log and proceed with the attachments already discovered (partial is better than none).

### Testing Strategy

- Unit tests for attachment filtering logic (extension filter, size filter)
- Unit tests for attachment key generation
- Integration/behavioral tests for the discovery → diff → ingest flow (mocked Confluence API responses with `children.attachment` data, mocked Unique API)
- Helm CI tests: Add attachment config values to existing `ci/*.yaml` test fixtures

## Out of Scope

- Ingesting external file URLs from page HTML body (v1 href parsing approach)
- Attachment thumbnails or preview generation
- Attachment comments/metadata beyond what Confluence API provides
- Cross-page attachment deduplication (same file on multiple pages = ingested per page)
- Attachment-only sync without pages (attachments always discovered via parent pages)

## Tasks

1. **Add attachment config schema** — Create Zod schema for `ingestion.attachments` (enabled, allowedExtensions, maxFileSizeBytes). Add to existing ingestion schema and tenant config validation. Update `.env.example` documentation.

2. **Add attachment types** — Define `ConfluenceAttachment` Zod schema and type (id, title, version.when, extensions.mediaType, extensions.fileSize, _links.download). Extend `confluencePageSchema` to include optional `children.attachment` with paginated response.

3. **Add conditional expand for attachments in API clients** — When `attachments.enabled`, append `children.attachment,children.attachment.version,children.attachment.extensions` to the expand parameter in `searchPagesByLabel`, `getDescendantPages`, and `getPageById` for both Cloud and DC clients. Add pagination support for pages with >25 attachments.

4. **Extract attachment metadata in scanner** — During `mapToDiscoveredPages`, extract attachment data from `children.attachment.results[]`. Apply extension and size filters. Return `DiscoveredAttachment[]` alongside `DiscoveredPage[]`.

5. **Extend diffing to include attachments** — Include attachment keys in `FileDiffService.computeDiff()` input alongside page keys. Attachment keys use format `pageId/attachmentId` (relative to the space partialKey).

6. **Add `getAttachmentDownloadStream` to API clients** — Implement authenticated streaming download from Confluence's attachment download URL. Convert web stream to Node.js Readable. Goes through existing `RateLimitedHttpClient`.

7. **Add attachment ingestion with streaming** — Implement `ingestAttachment()` on `IngestionService`: register → stream download from Confluence → PUT stream to writeUrl → finalize. Follow SharePoint connector streaming pattern (Readable.fromWeb, undici body: stream). Include rollback on failure.

8. **Orchestrate attachment sync in synchronization service** — Wire attachment discovery, diffing, and ingestion into `ConfluenceSynchronizationService.synchronize()`. After ingesting a page, ingest its new/updated attachments. Handle concurrency and error isolation per attachment.

9. **Update Helm chart and values** — Add `attachments` config to `values.yaml`, `values.schema.json`, `templates/tenant-config.yaml`, and CI test fixtures.

10. **Update monorepo gitops-resources** — Add attachment config defaults to `defaults.yaml`, `prod.yaml`, and `QA/values.yaml` in monorepo deploy files.
