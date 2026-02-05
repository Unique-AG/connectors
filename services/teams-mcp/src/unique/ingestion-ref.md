## structure

- **Root scope** → folders **&lt;subject - date&gt;** → **transcript.vtt** + metadata (e.g. participants, date).

You want to find transcripts by **date** and **participants**.

---

## Fit: use **POST /content/infos** with **metadataFilter**

**POST …/content/infos** with **metadataFilter** (UniqueQL) is the right endpoint. The rule is applied to content fields, including **metadata** and **title**, and supports combining conditions with `and` / `or`.

UniqueQL format:

- **path**: array of field names (top-level content fields or nested, e.g. `metadata.date`).
- **operator**: `equals`, `contains`, `in`, `notEquals`, etc.
- **value**: scalar or array depending on operator.

Existing tests use paths like `['folderIdPath']`, `['title']`; for your case you’d use `['metadata', 'date']` and `['metadata', 'participants']`.

### Example: date + participants

```json
{
  "metadataFilter": {
    "and": [
      { "path": ["metadata", "date"], "operator": "equals", "value": "2024-01-15" },
      { "path": ["metadata", "participants"], "operator": "contains", "value": "Jane" }
    ]
  },
  "skip": 0,
  "take": 50
}
```

- If **date** is stored in another shape (e.g. ISO string, or under another key), adjust **path** and **value** (e.g. `["metadata", "meetingDate"]`).
- If **participants** is an array, use **contains** for “any participant name contains this string”, or **in** if the backend supports it for array membership; exact format depends on how ingestion stores it.

### Restrict to root scope (folder)

You can add scope to the same rule so results are only from your root scope (or a given folder):

```json
{
  "metadataFilter": {
    "and": [
      { "path": ["ownerId"], "operator": "equals", "value": "<root-scope-id>" },
      { "path": ["metadata", "date"], "operator": "equals", "value": "2024-01-15" },
      { "path": ["metadata", "participants"], "operator": "contains", "value": "Jane" }
    ]
  },
  "skip": 0,
  "take": 50
}
```

Or, if you identify “under this folder” by path:

```json
{
  "metadataFilter": {
    "and": [
      { "path": ["folderIdPath"], "operator": "contains", "value": "uniquepathid://<root-scope-id>" },
      { "path": ["metadata", "date"], "operator": "equals", "value": "2024-01-15" },
      { "path": ["metadata", "participants"], "operator": "contains", "value": "Jane" }
    ]
  },
  "skip": 0,
  "take": 50
}
```

So: **date + participants (and optionally scope) can all be expressed in one POST /content/infos request** using **metadataFilter**.

---

## Optional: also match by folder name (subject + date)

If folder names are like `Q4 Planning - 2024-01-15`, you can also match by **title** (if the API exposes title of the folder or of the transcript content) in the same **metadataFilter**, e.g.:

```json
{
  "path": ["title"],
  "operator": "contains",
  "value": "2024-01-15"
}
```

Combine with the conditions above in the same **and** array.

---

## POST /content/search vs POST /content/infos

- **POST /content/search**  
  - Uses **where** (ContentWhereInput).  
  - Public DTO currently exposes **ownerId**, **key**, **title**, **id**, **url**, **parentId** — **not** **metadata**.  
  - So you can search by scope (ownerId), title, key, etc., but **not** by metadata (date, participants) on this endpoint today.

- **POST /content/infos**  
  - Uses **metadataFilter** (UniqueQL) which can target **metadata** (and other content fields).  
  - So **infos** is the one that fits “find relevant transcript by date + participants” (and optionally by scope via **ownerId** or **folderIdPath** in the same rule).

---

## Summary

- **Finding transcripts by date + participants (and optionally by root scope/folder):**  
  Use **POST /content/infos** with **metadataFilter**:
  - `path: ["metadata", "date"]`, `operator: "equals"`, `value: "<date>"`.
  - `path: ["metadata", "participants"]`, `operator: "contains"` (or `"in"` if supported for arrays), `value: "<name>"`.
  - Add `path: ["ownerId"], operator: "equals", value: "<root-scope-id>"` (or **folderIdPath** + **contains**) to limit to your folder tree.
- **Finding by scope + title only (no metadata):**  
  You can use **POST /content/search** with **where** (e.g. **ownerId** + **title**).
- If you later need **full-text search over transcript text** (chunks) and also filter by date/participants, that would require either a different search API or extending **ContentWhereInput** to include **metadata** and using **POST /content/search** with a combined **where** (ownerId + metadata).