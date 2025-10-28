import type { SharepointContentItem } from '../../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { IngestionApiResponse } from '../../unique-api/unique-api.types';

export interface ProcessingContext {
  correlationId: string;
  pipelineItem: SharepointContentItem;
  knowledgeBaseUrl: string;
  uploadUrl?: string;
  uniqueContentId?: string;
  contentBuffer?: Buffer;
  fileSize?: number;

  startTime: Date;
  mimeType?: string;
  registrationResponse?: IngestionApiResponse;
}

export interface PipelineResult {
  success: boolean;
}

export const PipelineStep = {
  ContentFetching: 'ContentFetching',
  AspxProcessing: 'AspxProcessing',
  ContentRegistration: 'ContentRegistration',
  StorageUpload: 'StorageUpload',
  IngestionFinalization: 'IngestionFinalization',
} as const;
export type PipelineStep = (typeof PipelineStep)[keyof typeof PipelineStep];
