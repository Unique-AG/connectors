export const SEARCH_CONFIG = {
  // Emails per page of one backend request: one Graph request (query × mailbox × folder) or one
  // semantic search.
  pageSize: { min: 1, max: 50, default: 25 },
  maxQueriesPerBackend: 3,
  maxCursorsPerFetch: 10,
  // Microsoft Graph returns at most 1,000 results for one $search chain. Semantic chains stop at
  // the same depth so an unfiltered semantic search cannot page through a whole mailbox.
  maxResultsPerChain: 1000,
  cursorRetentionDays: 30,
} as const;
