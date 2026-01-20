export const DEFAULT_PROCESSING_CONCURRENCY = 1 as const;
export const DEFAULT_STEP_TIMEOUT_SECONDS = 30 as const;
export const DEFAULT_MAX_FILE_SIZE_BYTES = 209715200 as const; // 200MB

export const DEFAULT_GRAPH_RATE_LIMIT_PER_MINUTE_THOUSANDS = 780 as const; // this is the maximum number of requests allowed per minute for the Microsoft Graph API

export const DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE = 100 as const;

export const GRAPH_API_PAGE_SIZE = 300 as const;

export const HTTP_STATUS_OK_MAX = 299 as const;

export const DEFAULT_MIME_TYPE = 'application/octet-stream' as const;

export const CRON_EVERY_15_MINUTES = '*/15 * * * *' as const;
