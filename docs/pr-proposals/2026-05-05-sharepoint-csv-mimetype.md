# PR Proposal

## Ticket

UN-20317

## Title

fix(sharepoint-connector): remap CSV mimeType from SharePoint to text/csv

## Description

- SharePoint returns `application/vnd.ms-excel` for `.csv` files; the ingestion service rejects this mimeType, silently dropping CSVs (1,416 files affected in one PROD tenant).
- Adds a `processing.mimeTypeOverridesByExtension` config map (suffix → mimeType) with a default of `.csv` → `text/csv`; user-supplied value replaces the default wholesale. Suffix matching is longest-match-wins so multi-segment suffixes like `.tar.gz` work.
- Resolves mimeType through a shared helper used by both the file filter and content-registration step, so the canonical mimeType is the single source of truth in the pipeline.
- Updates the Helm chart (`values.yaml`, `values.schema.json`, `templates/tenant-config.yaml`, regenerated chart `README.md`, helm tests), example tenant configs, and operator docs (`configuration.md`, `deployment.md`, `faq.md`) to cover the new field and the corrected default `allowedMimeTypes`.
- Includes a migration note for tenants who previously added `application/vnd.ms-excel` to `allowedMimeTypes` as a workaround.
