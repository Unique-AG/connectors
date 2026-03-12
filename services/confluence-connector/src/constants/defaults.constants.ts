export const DEFAULT_PROCESSING_CONCURRENCY = 1 as const;
export const CRON_EVERY_15_MINUTES = '*/15 * * * *' as const;

export const DEFAULT_UNIQUE_API_RATE_LIMIT_PER_MINUTE = 100 as const;

export const DEFAULT_INGEST_SINGLE_LABEL = 'ai-ingest' as const;
export const DEFAULT_INGEST_ALL_LABEL = 'ai-ingest-all' as const;

export const DEFAULT_MAX_FILE_SIZE_BYTES = 209_715_200 as const; // 200MB
export const DEFAULT_ALLOWED_EXTENSIONS = [
  'pdf',
  'doc',
  'docx',
  'xls',
  'xlsx',
  'pptx',
  'txt',
  'csv',
  'html',
] as const;
