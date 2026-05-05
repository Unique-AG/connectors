# Design: SharePoint connector mimeType override by extension

**Ticket:** UN-20317

## Problem

SharePoint returns `application/vnd.ms-excel` as the mimeType for `.csv` files. The SharePoint connector forwards this raw mimeType through its processing pipeline, and the ingestion service rejects it with HTTP 400 "Invalid file type". The failure is silent — files never reach the Content table and there is no user-visible signal. One PROD tenant has 1,416 files missing from their KB because of this.

The mimeType from SharePoint is unreliable for some extensions, but the file extension is authoritative. We need a way to map extension (suffix) → canonical mimeType inside the connector before that mimeType drives any downstream behavior (filter, content registration).

## Solution

### Overview

Add a configurable suffix-to-mimeType override map under `processing.*` config. A default mapping (`.csv` → `text/csv`) is applied so the bug is fixed out of the box; users can extend the map for any other extensions whose SharePoint-reported mimeType is wrong. The override is resolved at a single point in the pipeline so both the file filter and the content-registration step see the canonical mimeType.

### Architecture

**Config schema** (`processing.schema.ts`): a new `mimeTypeOverridesByExtension` field, a `Record<string, string>` (suffix → mimeType). Suffixes are normalized to lowercase including the leading dot. Default value: `{ '.csv': 'text/csv' }`. The default replaces wholesale when a user provides their own value (no merge) — users who want their own overrides AND the CSV fix must include `.csv` in their map. This is simpler and matches how `allowedMimeTypes` already behaves.

**Shared resolver** (`src/processing-pipeline/utils/resolve-mime-type.ts`, new file): pure function that takes a file name, the raw SharePoint mimeType, and the override map, and returns the canonical mimeType. Used by both the pipeline service and the file filter — single source of truth.

**Pipeline service** (`processing-pipeline.service.ts:127`): replace the inline `resolveMimeType` private method with a call to the new helper. The result populates `context.mimeType` once and flows through every downstream step (content registration, upload, finalization).

**File filter** (`file-filter.service.ts:44`): currently reads `item.file?.mimeType` directly to check against `allowedMimeTypes`. Update it to use the shared helper so the allow-list check operates on the canonical mimeType.

**Helm chart** (`deploy/helm-charts/sharepoint-connector/`):
- `values.yaml`: add `connectorConfig.processing.mimeTypeOverridesByExtension` with default `.csv: text/csv` and `text/csv` added to the existing `allowedMimeTypes` defaults.
- `templates/tenant-config.yaml`: render the new field into the rendered tenant config.
- `values.schema.json`: schema for the new field (object with string values; suffix-pattern key validation matches the app schema).
- `README.md`: regenerated via `helm-docs.sh` (auto-generated from `values.yaml`).
- `tests/regressions._test.yaml`: a snapshot/assertion case that the override map renders correctly.

**Example tenant configs**: `default-tenant-config.example-config-file.yaml` and `default-tenant-config.example-sharepoint-list.yaml` get `text/csv` added to `processing.allowedMimeTypes` and a commented-out `mimeTypeOverridesByExtension` block showing the default.

**Documentation**:
- `docs/operator/configuration.md`: add a row in the processing-config table and a section explaining the override map (default, replace-not-merge semantics, suffix matching with longest-match-wins).
- `docs/operator/deployment.md`: if its inline example covers `processing.*`, mirror the same `text/csv` addition.
- `docs/faq.md`: extend the "Why aren't my CSV files being ingested?" angle — mention that the connector now rewrites `.csv` to `text/csv` by default.

### Error Handling

Resolution is pure — given a file name and the override map, it returns a string. Edge cases:

- **No matching suffix** (e.g. `README`, or no entry matches): fall back to raw mimeType, then `DEFAULT_MIME_TYPE`. Behavior unchanged from today for non-overridden files.
- **Mixed case** (`.CSV`, `Foo.Csv`, `.Tar.Gz`): file name and map keys are lowercased before matching.
- **Multi-segment suffixes** (`archive.tar.gz`): a user-configured `.tar.gz` matches; if both `.tar.gz` and `.gz` are configured, longest match wins. Implementation: sort map keys by length descending once at startup; on each call, find the first key the lowercased file name `endsWith()`.
- **Empty filename**: nothing matches, fall through.

Config validation: keys must match `^(\.[a-z0-9]+)+$` after lowercase normalization (one or more `.alphanumeric` segments). This permits `.csv`, `.tar.gz`, `.xls.zip`, etc., and rejects malformed keys like `csv` (missing dot), `.` (empty segment), or `.foo bar` (space). Empty mimeType values are rejected. Bad config fails fast at startup, same as the rest of the `processing.*` schema.

### Testing Strategy

Pure unit tests for the resolver (`resolve-mime-type.spec.ts`) — these are exactly the case the AGENTS rule allows tests for ("pure standalone functions"):

- Default `.csv` → `text/csv` mapping
- Custom override merged with defaults
- User override of the default (e.g. user maps `.csv` → something else)
- Case-insensitive suffix match
- Multi-segment suffix match (`.tar.gz` configured → `archive.tar.gz` resolves to its mimeType)
- Longest-match wins (both `.tar.gz` and `.gz` configured → `archive.tar.gz` picks `.tar.gz`)
- Single-segment match still wins for shorter names (`.gz` configured → `notes.gz` resolves correctly)
- Files with no extension fall through
- Falls back to `item.file.mimeType` when no override matches
- Falls back to `DEFAULT_MIME_TYPE` when no mimeType at all

Behavioral coverage in the existing filter and pipeline specs (use existing test setup, no new harness):

- `file-filter.service.spec.ts`: `.csv` file with raw mimeType `application/vnd.ms-excel` and `allowedMimeTypes: ['text/csv']` is now accepted.
- `file-filter.service.spec.ts`: `.xls` file with raw mimeType `application/vnd.ms-excel` and `allowedMimeTypes: ['text/csv']` is rejected (regression guard for legacy Excel).
- `processing-pipeline.service.spec.ts` / `content-registration.step.spec.ts`: registration request for a `.csv` file carries `text/csv`.

## Out of Scope

- **User-visible warning for files filtered out or rejected by the ingestion service.** The ticket flags that the failure is silent. Surfacing per-file rejection reasons (`.xls` skipped, etc.) is its own observability ticket — touches different layers and would balloon scope.
- **Ingestion-service-side fix** to accept `application/vnd.ms-excel` and route by extension. Decided against; would help future connectors but couples this fix to a platform release.
- **Default mappings for extensions other than `.csv`.** We only set a default where there is confirmed evidence. Other extensions remain opt-in.
- **Backfill of the 1,416 already-rejected files.** Once the connector ships, the next sync cycle picks them up and ingests them — no special migration needed.

## Tasks

1. **Add `mimeTypeOverridesByExtension` to processing config schema** — Extend `services/sharepoint-connector/src/config/processing.schema.ts` with a `Record<string, string>` field. Validate keys against `^(\.[a-z0-9]+)+$` after lowercase normalization, reject empty mimeType values. Default value: `{ '.csv': 'text/csv' }`. User-supplied value replaces the default wholesale (no merge).

2. **Extract a shared `resolveMimeType` helper** — Create `services/sharepoint-connector/src/processing-pipeline/utils/resolve-mime-type.ts` that takes a file name, the raw SharePoint mimeType, and the override map, and returns the canonical mimeType. Implements lowercase normalization, longest-suffix-wins matching, fallback to raw mimeType, then `DEFAULT_MIME_TYPE`. Pure function, no Nest decorators.

3. **Add unit tests for `resolveMimeType`** — Cover default `.csv` mapping, custom suffix override, user override of default, case-insensitive matching, multi-segment suffixes (`.tar.gz`), longest-match-wins, fallback to raw mimeType, fallback to `DEFAULT_MIME_TYPE`, no-extension files.

4. **Wire resolver into the pipeline service** — Replace the inline `resolveMimeType` private method in `services/sharepoint-connector/src/processing-pipeline/processing-pipeline.service.ts` with a call to the new helper, sourcing the override map from `processing.mimeTypeOverridesByExtension` config.

5. **Wire resolver into the file filter** — Update `services/sharepoint-connector/src/microsoft-apis/graph/file-filter.service.ts` to use the same helper instead of reading `item.file?.mimeType` directly. Allow-list check now runs against the canonical mimeType.

6. **Update filter and pipeline specs for the new behavior** — Add behavioral cases: `.csv` with raw `application/vnd.ms-excel` is accepted when `allowedMimeTypes` contains `text/csv`; `.xls` with raw `application/vnd.ms-excel` is rejected when `allowedMimeTypes` doesn't contain it; content-registration request for a `.csv` carries `text/csv`.

7. **Update example tenant configs** — In `services/sharepoint-connector/default-tenant-config.example-config-file.yaml` and `default-tenant-config.example-sharepoint-list.yaml`, add `text/csv` to `processing.allowedMimeTypes` and add a commented-out `mimeTypeOverridesByExtension` block showing the default for discoverability.

8. **Update Helm chart** — In `services/sharepoint-connector/deploy/helm-charts/sharepoint-connector/`:
    - `values.yaml`: add `connectorConfig.processing.mimeTypeOverridesByExtension: { .csv: text/csv }` with `helm-docs` annotations, and add `text/csv` to the existing `allowedMimeTypes` defaults.
    - `templates/tenant-config.yaml`: render the new field into the tenant config (only when set).
    - `values.schema.json`: add schema entry for the new field (object with string values, key pattern matching the app schema).
    - Run `deploy/helm-charts/helm-docs.sh` to regenerate the chart `README.md`.
    - `tests/regressions._test.yaml`: extend or add a case that asserts the rendered tenant config carries `mimeTypeOverridesByExtension` with the default.

9. **Update operator documentation** — In `services/sharepoint-connector/docs/`:
    - `operator/configuration.md`: add a row to the processing-config table for `mimeTypeOverridesByExtension`, and a short subsection explaining default, replace-not-merge semantics, and longest-suffix-match.
    - `operator/deployment.md`: mirror the example update so the inline `processing.*` snippet stays in sync.
    - `faq.md`: extend the existing "why aren't my files being ingested" content to mention the new override and call out the `.csv` → `text/csv` default.

10. **Update CHANGELOG / migration note** — Add a note under the connector's CHANGELOG describing the bug fix and a migration tip: tenants who previously added `application/vnd.ms-excel` to `allowedMimeTypes` to ingest CSVs should replace it with `text/csv` (and remove `application/vnd.ms-excel` if they don't actually want `.xls` files).
