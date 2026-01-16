import type { SharepointContentItem } from '../../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { SharepointSyncContext } from '../../sharepoint-synchronization/sharepoint-sync-context.interface';
import {
  ContentMetadata,
  IngestionApiResponse,
} from '../../unique-api/unique-file-ingestion/unique-file-ingestion.types';

export interface ProcessingContext {
  syncContext: SharepointSyncContext;
  correlationId: string;
  pipelineItem: SharepointContentItem;
  knowledgeBaseUrl: string;
  targetScopeId: string;
  uploadUrl?: string;
  uniqueContentId?: string;
  uploadSucceeded?: boolean;
  htmlContent?: string;
  fileSize?: number;
  startTime: Date;
  mimeType?: string;
  registrationResponse?: IngestionApiResponse;
  fileStatus: 'new' | 'updated';
  metadata?: ContentMetadata;
}

export interface PipelineResult {
  success: boolean;
}

export const PipelineStep = {
  AspxProcessing: 'AspxProcessing',
  ContentRegistration: 'ContentRegistration',
  UploadContent: 'UploadContent',
  IngestionFinalization: 'IngestionFinalization',
} as const;
export type PipelineStep = (typeof PipelineStep)[keyof typeof PipelineStep];
