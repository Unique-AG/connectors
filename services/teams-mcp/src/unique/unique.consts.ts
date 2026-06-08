export const UNIQUE_FETCH = Symbol('UNIQUE_FETCH');

/**
 * Source identity for Teams-ingested content. Hardcoded as a fixed platform
 * contract: every transcript/recording is attributed to a single shared
 * org-level "Microsoft Teams" source (mirrors SharePoint).
 */
export const TEAMS_SOURCE_KIND = 'MICROSOFT_365_TEAMS' as const;
export const TEAMS_SOURCE_NAME = 'Microsoft Teams' as const;
