import type {
  ContentRegistrationRequest,
  FileDiffItem,
  FileDiffResponse,
  IngestionApiResponse,
  IngestionFinalizationRequest,
  UploadContentRequest,
} from "../ingestion/ingestion.types";

export interface UniqueApiIngestion {
  registerContent(
    request: ContentRegistrationRequest,
  ): Promise<IngestionApiResponse>;
  streamUpload(request: UploadContentRequest): Promise<void>;
  finalizeIngestion(
    request: IngestionFinalizationRequest,
  ): Promise<{ id: string }>;
  performFileDiff(
    fileList: FileDiffItem[],
    partialKey: string,
    sourceKind: string,
    sourceName: string,
  ): Promise<FileDiffResponse>;
}
