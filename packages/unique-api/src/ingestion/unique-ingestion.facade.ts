import {
  ContentUpdateMetadataMutationInput,
  ContentUpdateMetadataResponse,
} from './ingestion.queries';
import type {
  ContentRegistrationRequest,
  FileDiffItem,
  FileDiffResponse,
  IngestionApiResponse,
  IngestionFinalizationRequest,
  IngestionState,
} from './ingestion.types';

export interface UniqueIngestionFacade {
  registerContent(request: ContentRegistrationRequest): Promise<IngestionApiResponse>;
  finalizeIngestion(request: IngestionFinalizationRequest): Promise<{ id: string }>;
  performFileDiff(
    fileList: FileDiffItem[],
    partialKey: string,
    sourceKind: string,
    sourceName: string,
  ): Promise<FileDiffResponse>;
  updateMetadata(
    request: ContentUpdateMetadataMutationInput,
  ): Promise<ContentUpdateMetadataResponse>;
  getIngestionStats(scopeId: string): Promise<Partial<Record<IngestionState, number>>>;
}
