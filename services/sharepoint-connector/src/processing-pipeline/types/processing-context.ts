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

export const PipelineStep = {
  ContentFetching: 'ContentFetching',
  ContentRegistration: 'ContentRegistration',
  StorageUpload: 'StorageUpload',
  IngestionFinalization:  'IngestionFinalization',
} as const;
export type PipelineStep = typeof PipelineStep[keyof typeof PipelineStep];