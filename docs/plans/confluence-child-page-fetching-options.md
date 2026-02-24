# Confluence: Child Page Fetching Options

## What we need per page
- `id`, `title`, `type`
- `version.when` (for file-diff)
- `space.id`, `space.key`, `space.name`
- `metadata.labels`
- `body.storage.value` (for processing so not at discovery stage)
- `_links.webui` (to build the page URL)

---

## Option 1: v1 CQL `ancestor=` (recommended)

When there is a single `ai-ingest-all` root:
```
GET /wiki/rest/api/content/search
  ?cql=ancestor=<rootPageId>
  &expand=metadata.labels,version,space
  &limit=250
```

When there are multiple `ai-ingest-all` roots, batch them into one request:
```
GET /wiki/rest/api/content/search
  ?cql=ancestor IN (<id1>, <id2>, <id3>)
  &expand=metadata.labels,version,space
  &limit=250
```

- Returns **all descendants at any depth** in a single request regardless of how many roots
- Includes all required fields including labels and space details
- Handles arbitrarily deep page trees automatically with no recursion needed
- Pagination via `_links.next` for large result sets
- The `IN (...)` clause contains root page IDs (small number in practice), not children — so no risk of hitting URL length limits
- Edge case: if hundreds of pages are labeled with `ai-ingest-all`, the URL could get too long. Fix is trivial — chunk the root IDs into batches of e.g. 50 and fire one request per chunk, then merge results

---

## Option 2: v2 `direct-children` + batch CQL fetch

```
GET /wiki/api/v2/pages/<id>/direct-children
GET /wiki/rest/api/content/search?cql=id="<id1>" OR id="<id2>"&expand=metadata.labels,version,space
```

- 2 requests per level instead of N+1
- Still requires manual recursion for deep trees
- Good middle ground if `ancestor=` is not desirable for some reason

---

## Option 3: v2 `direct-children` + individual CQL fetch (current implementation, avoid)

```
GET /wiki/api/v2/pages/<id>/direct-children
GET /wiki/rest/api/content/search?cql=id=<childId>&expand=...  (× N children)
```

- Only fetches one level at a time — must recurse manually
- N+1 requests per level of nesting
- Current v2 connector implementation does this

---

## Why v2 bulk pages doesn't work

```
GET /wiki/api/v2/pages?id=<id1>&id=<id2>&include-labels=true
```

- `include-labels=true` or expand=labels do not work, labels are not supported in this endpoint
- Labels require a separate `/wiki/api/v2/pages/<id>/labels` call per page, this is the blocker
- No `space.key`/`space.name` only `spaceId` which is not a blocker because we have these in our scope
