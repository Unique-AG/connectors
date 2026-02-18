import {
  ContentUpdateMetadataMutationInput,
  ContentUpdateMetadataResponse,
} from '../ingestion/ingestion.queries';
import type {
  ContentRegistrationRequest,
  FileDiffItem,
  FileDiffResponse,
  IngestionApiResponse,
  IngestionFinalizationRequest,
} from '../ingestion/ingestion.types';

export interface UniqueApiIngestion {
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
}
