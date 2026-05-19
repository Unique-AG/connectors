# UN-14316 / UN-20384: Inline Confluence image attachments into page HTML

## Context

The Confluence connector currently ingests content in two separate passes:

1. `fetchAndIngestPages` — pulls page bodies (Confluence storage XML from `body.storage.value`) and uploads them as one ingestion artifact per page.
2. `ingestAttachments` — separately downloads each attachment binary (including images) and uploads it as its own ingestion artifact.

Downstream this produces decoupled artifacts that must be re-correlated. Images especially are most useful when they live inside the page they belong to.

**Goal:** a single ingestion artifact per page. When a page references an image that is a Confluence attachment, download it, base64-encode it, replace the `<ac:image>` macro with `<img src="data:...">`, and upload the enriched HTML as the page artifact. Image attachments stop being ingested standalone (only when successfully inlined). Non-image attachments are unchanged.

## Scope decisions

- **Inline:** images attached to the page being ingested, plus images attached to other pages in the same Confluence instance (cross-page `<ri:attachment>` with `<ri:page>` child). Both authenticated via the existing Confluence client.
- **Don't inline:** `<ac:image><ri:url ri:value="https://..."/></ac:image>` external URLs. SSRF risk, no auth model, marginal value. Left untouched in the HTML.
- **No new feature flag.** New behavior is default; image attachments are removed from the standalone ingestion pass only when successfully inlined. Orphan or failed-to-inline images still get ingested standalone (safety net).

## Confluence storage format

Verified against Atlassian docs. All page-embedded images are wrapped in `<ac:image>`. There is no plain `<img>` in storage format. Three reference shapes:

```xml
<!-- current-page attachment -->
<ac:image>
  <ri:attachment ri:filename="diagram.png"/>
</ac:image>

<!-- cross-page attachment -->
<ac:image>
  <ri:attachment ri:filename="diagram.png">
    <ri:page ri:space-key="TST" ri:content-title="Test Page"/>
  </ri:attachment>
</ac:image>

<!-- external URL -->
<ac:image>
  <ri:url ri:value="https://example.com/x.png"/>
</ac:image>
```

`<ac:image>` carries presentational attributes: `ac:alt, ac:title, ac:width, ac:height, ac:align, ac:class, ac:style, ac:border, ac:thumbnail, ac:vspace, ac:hspace`. We map `ac:alt → alt`, `ac:title → title`, `ac:width → width`, `ac:height → height`. The rest are Confluence-renderer hints and are dropped.

## Approach

Insert a new `PageImageInliner` service between `contentFetcher.fetchPageContent()` and `ingestionService.ingestPage()` in the orchestrator. The inliner:

1. Parses the storage-format body using **htmlparser2** with `withStartIndices: true` to find every `<ac:image>...</ac:image>` block and record its `(startByte, endByte, parsedContent)`.
2. Resolves the target attachment for each block:
   - current-page → match by `ri:filename` against the passed-in attachment list,
   - cross-page → on-demand API lookup, cached per-sync,
   - external `<ri:url>` → skip.
3. Downloads the resolved image via existing `confluenceApiClient.getAttachmentDownloadStream()`, accumulates into a Buffer, base64-encodes it, builds `<img src="data:{mediaType};base64,{...}" alt="..." />`.
4. **Surgical splice** — walks the original body string and replaces the recorded byte ranges with the new `<img>` tags in a single pass. Everything outside `<ac:image>` blocks is preserved byte-for-byte (no DOM round-trip).
5. Returns `{ page: FetchedPage, inlinedAttachmentIds: Set<string> }`.

The orchestrator accumulates `inlinedAttachmentIds` across all pages, then filters the attachment-pass list before `ingestAttachments`.

### Why htmlparser2 with surgical splice

- Confluence storage format is XHTML-ish but not always strictly valid XML (CDATA in code-block macros, unescaped entities). htmlparser2 in `xmlMode: true` is tolerant.
- We modify only `<ac:image>...</ac:image>` blocks. Surgical splice preserves the rest of the document byte-for-byte. No DOM round-trip means no risk of re-serialization mutating attribute quoting, self-closing forms, or whitespace elsewhere.
- htmlparser2 is small (~80 KB), well-maintained, and is the engine cheerio sits on top of — no new tolerance/correctness surface compared to cheerio's `xmlMode`.

### Cross-page resolution

When `<ri:attachment>` has an `<ri:page>` child, look up the target page's attachments via the Confluence API. Cache results on the inliner instance keyed by `(spaceKey, contentTitle)`. The cache is per-sync (the inliner is created per-sync).

Add to `ConfluenceApiClient` (both Cloud and Data Center): `fetchPageAttachmentsByTitle(spaceKey: string, title: string): Promise<DiscoveredAttachment[]>`.

### Failure handling

For each `<ac:image>` block, on any of these conditions we leave the macro untouched and continue (warn log):

- `<ri:url>` external URL (always skipped — by design).
- Filename not found in the page's (or target page's) attachments.
- Target attachment's `mediaType` is not `image/*`.
- Image size exceeds `ingestion.attachments.maxFileSizeMb`.
- Download stream throws.
- Cross-page lookup returns 404 / empty.

In all these cases, the attachment id is **not** added to `inlinedAttachmentIds`, so if it was queued for standalone ingestion it will still go through `ingestAttachment` (safety net).

### Size and streaming

Page upload remains buffered (`uploadBuffer`) — `registerContent` requires `byteSize` up-front. We buffer a larger body. Memory ceiling per in-flight page is roughly `pageHtmlSize + sum(imageSize * 1.34)`, bounded by `processing.concurrency` and the per-image `maxFileSizeMb` cap.

## Files to change

| File | Change |
|---|---|
| `src/synchronization/page-image-inliner.ts` (new) | `PageImageInliner` class. Method: `inlineImages(page, pageAttachments) → { page, inlinedAttachmentIds }`. Holds the cross-page lookup cache. |
| `src/synchronization/__tests__/page-image-inliner.spec.ts` (new) | Unit tests (last task). |
| `src/synchronization/confluence-synchronization.service.ts` | Inject inliner. Build `pageId → image-attachments` map. Call `inliner.inlineImages` between `fetchPageContent` and `ingestPage`. Accumulate `inlinedAttachmentIds`. Filter attachment list before attachment pass. |
| `src/synchronization/__tests__/confluence-synchronization.service.spec.ts` | Add cases for inlined / fallback paths (last task). |
| `src/confluence-api/confluence-api-client.ts` (abstract) | Add `fetchPageAttachmentsByTitle(spaceKey, title)`. |
| `src/confluence-api/cloud-api-client.ts` | Implement via v2 attachments endpoint (resolve page by space + title first). |
| `src/confluence-api/data-center-api-client.ts` | Implement via DC `/rest/api/content` with `spaceKey` + `title` + `expand=children.attachment`. |
| `src/synchronization/__mocks__/sync.fixtures.ts` | Add fixtures: current-page, cross-page, external-URL, multi-image, image-with-attributes. |
| Synchronization DI wiring | Register `PageImageInliner`. |
| `services/confluence-connector/package.json` | Add `htmlparser2`. |

No change to `FetchedPage` / `DiscoveredAttachment` schemas. No change to `IngestionService` signatures.

## Reused existing utilities

- `ConfluenceApiClient.getAttachmentDownloadStream` — already returns `Readable` with auth + rate limiting.
- `RateLimitedHttpClient.rateLimitedStreamRequest` — image downloads inherit the existing rate limiter.
- `IngestionService.ingestPage` — signature unchanged.
- `pLimit(concurrency)` pattern in `fetchAndIngestPages` — keep.
- Image classification: `mediaType.startsWith('image/')`.

## Execution workflow

- **Branch:** `feat/UN-14316-inline-page-images` off `main`.
- **One commit per task.** Do not push.
- **Unit tests last.** All preceding tasks add/modify production code; the final task adds tests.
- Repo conventions: scope `confluence-connector` for per-package files; scope `deps` for `pnpm-lock.yaml` / root `package.json`. No `Co-Authored-By: Claude` trailer. Stage files explicitly by path. Use `assert` from `node:assert` for invariants. Block-form `if` statements. Avoid `as` casts.
- Before the final test commit: run `pnpm biome check`, `pnpm tsc -b`, `pnpm vitest run`.

### Task list (each = one commit)

1. Create feature branch.
2. Add `htmlparser2` dependency.
3. Add `fetchPageAttachmentsByTitle` to `ConfluenceApiClient` (abstract + cloud + data-center).
4. Create `PageImageInliner` service.
5. Wire `PageImageInliner` into the synchronization DI module.
6. Update `ConfluenceSynchronizationService` orchestration.
7. Add test fixtures.
8. Run biome + tsc + vitest, fix anything, then add unit tests.
9. Update user-facing documentation to reflect the new inline-image behavior:
   - `docs/README.md` — rewrite the "Image Ingestion" section to describe inlining as the default for page-attached images; update the high-level sync flow diagram (the second pass is no longer "Ingest Attachments" for images, only for non-image attachments) and the content sync sequence diagram (no separate image stream).
   - `docs/technical/flows.md` — adjust flow descriptions for the merged page+image ingestion path; note the cross-page resolution and the orphan/failure safety net.
   - `docs/operator/configuration.md` — clarify that `attachments.imageOcr` now only affects standalone-ingested images (orphans / failed inlines).
   - `docs/faq.md` — add Q/A on what happens to images and how to spot orphan vs. inlined cases in logs.

## Test cases (final task)

### `page-image-inliner.spec.ts`

- single current-page image → swapped to `<img src="data:image/png;base64,...">` with correct mime + base64
- multiple images in one body → each swapped, byte ranges spliced without overlap
- `ac:alt`, `ac:width`, `ac:height`, `ac:title` → mapped to `<img alt width height title>`
- presentational attrs (`ac:align`, `ac:thumbnail`, `ac:vspace`, `ac:hspace`, `ac:border`, `ac:class`, `ac:style`) → dropped
- `<ri:url>` external image → macro untouched, no fetch made
- filename not in page attachments → macro untouched
- attachment present but mediaType is not `image/*` → macro untouched
- attachment exceeds `maxFileSizeMb` → macro untouched
- download stream throws → macro untouched, id NOT in inlined set
- cross-page reference → API client called once, image inlined, target attachment id added to `inlinedAttachmentIds`
- cross-page cache → two references to same `(spaceKey, title)` → one API call
- cross-page lookup returns empty → macro untouched
- body with surrounding content (whitespace, code macros containing CDATA) → byte-perfect preservation outside swapped regions
- empty body / body with no images → returns input unchanged, empty inlined set

### `confluence-synchronization.service.spec.ts`

- image attachment of a page → `ingestPage` called with body containing the data URI; `ingestAttachment` NOT called for that image
- inliner failed for image → `ingestAttachment` IS called for it (fallback)
- non-image attachment of the same page → `ingestAttachment` called normally
- image referenced from another page also being synced → not double-ingested
- image referenced from a page NOT being synced → cross-page lookup happens, image inlined, no double-ingest

## Verification

1. `pnpm install && pnpm biome check && pnpm tsc -b && pnpm vitest run` in `services/confluence-connector`.
2. Manual sanity run against `local-confluence-v8.5-docker-compose.yaml`:
   - Create a page with an inline image attachment + another page referencing a cross-space image. Run a sync.
   - The registered page body contains `<img src="data:image/png;base64,...` for both images. No `<ac:image>` macros remain.
   - Image attachments are absent from the standalone attachment ingestions.
   - An unreferenced image attachment IS still standalone-ingested.
   - External `<img>` references (via `<ri:url>`) are present unchanged.
3. Before any push: re-run biome + tsc + vitest, verify the PR scope `confluence-connector` against `.gitcommitizen` and `release-please-config.json`.
