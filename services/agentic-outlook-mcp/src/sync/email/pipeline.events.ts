import { Message } from "@microsoft/microsoft-graph-types";
import { TypeID } from "typeid-js";

export enum PipelineEvents {
  IngestRequested = 'pipeline.ingest.requested',
  IngestCompleted = 'pipeline.ingest.completed',
  IngestFailed = 'pipeline.ingest.failed',
  ProcessingRequested = 'pipeline.processing.requested',
  ProcessingCompleted = 'pipeline.processing.completed',
  ProcessFailed = 'pipeline.processing.failed',
  ChunkingRequested = 'pipeline.chunking.requested',
  ChunkingCompleted = 'pipeline.chunking.completed',
  ChunkingFailed = 'pipeline.chunking.failed',
  EmbeddingRequested = 'pipeline.embedding.requested',
  EmbeddingCompleted = 'pipeline.embedding.completed',
  EmbeddingFailed = 'pipeline.embedding.failed',
  IndexingRequested = 'pipeline.indexing.requested',
  IndexingCompleted = 'pipeline.indexing.completed',
  IndexingFailed = 'pipeline.indexing.failed',
}

export class IngestRequestedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
    public readonly message: Message,
  ) {}
}

export class IngestCompletedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
    public readonly emailId: TypeID<'email'>,
  ) {}
}

export class IngestFailedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
    public readonly messageId: string,
    public readonly error: string,
  ) {}
}

export class ProcessingRequestedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
  ) {}
}

export class ProcessingCompletedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
  ) {}
}

export class ProcessFailedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: string,
    public readonly error: string,
  ) {}
}

export class ChunkingRequestedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
  ) {}
}

export class ChunkingCompletedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
    // public readonly chunks: Array<{ id: string; content: string }>,
  ) {}
}

export class ChunkingFailedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: string,
    public readonly error: string,
  ) {}
}

export class EmbeddingRequestedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
    // public readonly chunks: Array<{ id: string; content: string }>,
  ) {}
}

export class EmbeddingCompletedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
    // public readonly embeddings: Array<{ chunkId: string; embedding: number[] }>,
  ) {}
}

export class EmbeddingFailedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: string,
    public readonly error: string,
  ) {}
}

export class IndexingRequestedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
    // public readonly embeddings: Array<{ chunkId: string; embedding: number[] }>,
  ) {}
}

export class IndexingCompletedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
  ) {}
}

export class IndexingFailedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: string,
    public readonly error: string,
  ) {}
}