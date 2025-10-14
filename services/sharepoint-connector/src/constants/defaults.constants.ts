export const DEFAULT_PROCESSING_CONCURRENCY = 1 as const;
export const DEFAULT_STEP_TIMEOUT_SECONDS = 30 as const;
export const DEFAULT_MAX_FILE_SIZE_BYTES = 209715200 as const; // 200MB

export const DEFAULT_GRAPH_RATE_LIMIT_PER_10_SECONDS = 10000 as const; // 10k requests per 10 seconds

export const HTTP_STATUS_OK_MAX = 299 as const;

export const DEFAULT_MIME_TYPE = 'application/octet-stream' as const;

export const CRON_EVERY_15_MINUTES = '*/15 * * * *' as const;
