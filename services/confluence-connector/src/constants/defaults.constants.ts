export const DEFAULT_PROCESSING_CONCURRENCY = 1 as const;
export const CRON_EVERY_15_MINUTES = '*/15 * * * *' as const;

export const DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE = 100 as const;

export const DEFAULT_INGEST_SINGLE_LABEL = 'ai-ingest' as const;
export const DEFAULT_INGEST_ALL_LABEL = 'ai-ingest-all' as const;

export const DEFAULT_HEALTH_SYNC_HISTORY_SIZE = 5 as const;
export const DEFAULT_HEALTH_SYNC_TENANT_FAILURE_THRESHOLD = 0.5 as const;
export const DEFAULT_HEALTH_CONNECTIVITY_TIMEOUT_MS = 3000 as const;

export const DEFAULT_MAX_FILE_SIZE_MB = 200 as const;
export const DEFAULT_ALLOWED_MIME_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'text/plain',
  'text/csv',
  'text/html',
  'image/png',
  'image/jpeg',
] as const;
