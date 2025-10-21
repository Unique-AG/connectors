import { Message } from '@microsoft/microsoft-graph-types';

export enum OrchestratorEventType {
  IngestRequested = 'ingest_requested',
  IngestCompleted = 'ingest_completed',
  IngestFailed = 'ingest_failed',
  ProcessingRequested = 'processing_requested',
  ProcessingCompleted = 'processing_completed',
  ProcessingFailed = 'processing_failed',
}

export interface BaseOrchestratorMessage {
  eventType: OrchestratorEventType;
  emailId: string;
  userProfileId: string;
  timestamp: string;
}

export interface IngestRequestedMessage extends BaseOrchestratorMessage {
  eventType: OrchestratorEventType.IngestRequested;
  folderId: string;
  message: Message;
}

export interface IngestCompletedMessage extends BaseOrchestratorMessage {
  eventType: OrchestratorEventType.IngestCompleted;
  folderId: string;
}

export interface IngestFailedMessage extends BaseOrchestratorMessage {
  eventType: OrchestratorEventType.IngestFailed;
  folderId: string;
  messageId: string;
  error: string;
}

export interface ProcessingRequestedMessage extends BaseOrchestratorMessage {
  eventType: OrchestratorEventType.ProcessingRequested;
}

export interface ProcessingCompletedMessage extends BaseOrchestratorMessage {
  eventType: OrchestratorEventType.ProcessingCompleted;
}

export interface ProcessingFailedMessage extends BaseOrchestratorMessage {
  eventType: OrchestratorEventType.ProcessingFailed;
  error: string;
}

export type OrchestratorMessage =
  | IngestRequestedMessage
  | IngestCompletedMessage
  | IngestFailedMessage
  | ProcessingRequestedMessage
  | ProcessingCompletedMessage
  | ProcessingFailedMessage;
