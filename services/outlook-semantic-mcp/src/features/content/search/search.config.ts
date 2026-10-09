export const SEARCH_CONFIG = {
  // Emails per page of one backend request: one Graph request (query × mailbox × folder) or one
  // semantic search.
  pageSize: { min: 1, max: 50, default: 25 },
  // KQL queries fan out per mailbox and folder, so one search_emails call can start dozens of Graph
  // requests. Their first pages share this many results. Later pages keep the size Graph puts in the
  // nextLink, which is never altered.
  firstCallGraphResultBudget: 200,
  minFirstPageSize: 5,
  maxQueriesPerBackend: 3,
  // One Microsoft Graph $batch.
  maxCursorsPerFetch: 20,
  // Microsoft Graph returns at most 1,000 results for one $search chain. Semantic chains stop at
  // the same depth so an unfiltered semantic search cannot page through a whole mailbox.
  maxResultsPerChain: 1000,
  // A 403 or 404 on a followed nextLink younger than this is trusted as lost mailbox access. An
  // older link may simply have stopped working, so it is reported `expired` and access is kept.
  // Graph does not document how long a nextLink lives.
  maxNextLinkAgeForAccessRevocationMinutes: 30,
  cursorRetentionDays: 30,
} as const;
