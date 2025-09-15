export interface ProcessingContext {
  correlationId: string;
  fileId: string;
  fileName: string;
  fileSize: number;

  siteUrl: string;
  libraryName: string;
  downloadUrl?: string;

  uploadUrl?: string;
  uniqueContentId?: string;
  contentBuffer?: Buffer | undefined;

  startTime: Date;

  metadata: Record<string, unknown>;
}

export interface PipelineResult {
  success: boolean;
  context: ProcessingContext;
  error?: Error;
  completedSteps: string[];
  totalDuration: number;
}

export interface JobResult {
  success: boolean;
  fileId: string;
  fileName: string;
  correlationId: string;
  duration: number;
  completedSteps: string[];
  error?: string;
}

export enum PipelineStep {
  TOKEN_VALIDATION = 'token-validation',
  CONTENT_FETCHING = 'content-fetching',
  CONTENT_REGISTRATION = 'content-registration',
  STORAGE_UPLOAD = 'storage-upload',
  INGESTION_FINALIZATION = 'ingestion-finalization',
}
