export const UNIQUE_FETCH = Symbol('UNIQUE_FETCH');

/**
 * Source identity for Teams-ingested content. Hardcoded as a fixed platform
 * contract: every transcript/recording is attributed to a single shared
 * org-level "Microsoft Teams" source (mirrors SharePoint).
 */
export const TEAMS_SOURCE_KIND = 'MICROSOFT_365_TEAMS' as const;
export const TEAMS_SOURCE_NAME = 'Microsoft Teams' as const;

/**
 * Content-type contracts for Teams-ingested media: transcripts are fetched and
 * stored as WebVTT, recordings as MP4. Fixed Graph content contracts, shared by
 * the download (`Accept` header), upload (`mimeType`), and lookup (metadata
 * filter) paths so the value cannot drift between them.
 */
export const TRANSCRIPT_MIME_TYPE = 'text/vtt' as const;
export const RECORDING_MIME_TYPE = 'video/mp4' as const;
