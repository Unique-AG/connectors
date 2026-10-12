export const SEARCH_CONFIG = {
  // Largest page of one backend request: one Graph request (query × mailbox × folder) or one
  // semantic search. The server picks every page size, the agent cannot.
  maxPageSize: 50,
  // Most results one search_emails or fetch_next_search_pages response may hold. Page sizes are
  // shrunk to fit before anything is fetched, and requests that do not fit are deferred to a cursor.
  // Later Graph pages keep the size Graph puts in the nextLink, which is never altered.
  maxResultsPerResponse: 150,
  // Smallest page a Graph request is shrunk to. Requests beyond `maxResultsPerResponse / minPageSize`
  // are deferred.
  minPageSize: 5,
  maxQueriesPerBackend: 3,
  // Each folder of a KQL query is its own Graph request.
  maxFoldersPerQuery: 10,
  // One Microsoft Graph $batch.
  maxCursorsPerFetch: 20,
  // Microsoft Graph returns at most 1,000 results for one $search chain.
  maxResultsPerChain: 1000,
  // Semantic search ranks every chunk in scope, so its pages go from the most relevant chunks to
  // noise and never run out on a real mailbox. A chain stops after `maxPages` pages.
  semanticSearch: { maxPages: 4 },
  // A 403 or 404 on a followed nextLink younger than this is trusted as lost mailbox access. An
  // older link may simply have stopped working, so it is reported `expired` and access is kept.
  // Graph does not document how long a nextLink lives.
  maxNextLinkAgeForAccessRevocationMinutes: 30,
  cursorRetentionDays: 30,
} as const;
