import { Message } from "@microsoft/microsoft-graph-types";
import { TypeID } from "typeid-js";

export enum PipelineEvents {
  IngestRequested = 'pipeline.ingest.requested',
  IngestCompleted = 'pipeline.ingest.completed',
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