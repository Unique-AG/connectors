import type { ProcessingMetadata } from './processing-metadata';

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

  metadata: ProcessingMetadata;
}

export interface PipelineResult {
  success: boolean;
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
  CONTENT_FETCHING = 'content-fetching',
  CONTENT_REGISTRATION = 'content-registration',
  STORAGE_UPLOAD = 'storage-upload',
  INGESTION_FINALIZATION = 'ingestion-finalization',
}
