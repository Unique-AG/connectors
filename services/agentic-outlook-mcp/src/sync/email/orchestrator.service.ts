import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2, OnEvent } from '@nestjs/event-emitter';
import { eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, emails as emailsTable } from '../../drizzle';
import {
  IngestCompletedEvent,
  IngestFailedEvent,
  IngestRequestedEvent,
  PipelineEvents,
  ProcessFailedEvent,
  ProcessingCompletedEvent,
  ProcessingRequestedEvent,
} from './pipeline.events';

@Injectable()
export class OrchestratorService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly amqpConnection: AmqpConnection,
    private readonly eventEmitter: EventEmitter2,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @OnEvent(PipelineEvents.IngestRequested)
  public async handleIngestRequested(event: IngestRequestedEvent) {
    const { userProfileId, folderId, message } = event;

    await this.amqpConnection.publish('email.pipeline', 'email.ingest', {
      message,
      userProfileId: userProfileId.toString(),
      folderId,
    });
  }

  @OnEvent(PipelineEvents.IngestCompleted)
  public async handleIngestCompleted(event: IngestCompletedEvent) {
    const { userProfileId, emailId } = event;

    this.logger.debug({
      msg: 'Ingest completed',
      emailId: emailId.toString(),
      userProfileId: userProfileId.toString(),
    });

    await this.db
      .update(emailsTable)
      .set({ ingestionStatus: 'ingested', ingestionLastAttemptAt: new Date().toISOString() })
      .where(eq(emailsTable.id, emailId.toString()));

    this.eventEmitter.emit(
      PipelineEvents.ProcessingRequested,
      new ProcessingRequestedEvent(userProfileId, emailId),
    );
  }

  @OnEvent(PipelineEvents.IngestFailed)
  public async handleIngestFailed(event: IngestFailedEvent) {
    const { messageId, error } = event;
    await this.db
      .update(emailsTable)
      .set({
        ingestionStatus: 'failed',
        ingestionLastError: error,
        ingestionLastAttemptAt: new Date().toISOString(),
        ingestionCompletedAt: new Date().toISOString(),
      })
      .where(eq(emailsTable.messageId, messageId));
  }

  @OnEvent(PipelineEvents.ProcessingRequested)
  public async handleProcessingRequested(event: ProcessingRequestedEvent) {
    const { userProfileId, emailId } = event;

    this.amqpConnection.publish('email.pipeline', 'email.process', {
      userProfileId: userProfileId.toString(),
      emailId: emailId.toString(),
    });
  }

  @OnEvent(PipelineEvents.ProcessingCompleted)
  public async handleProcessingCompleted(event: ProcessingCompletedEvent) {
    const { emailId } = event;

    await this.db
      .update(emailsTable)
      .set({ ingestionStatus: 'processed', ingestionLastAttemptAt: new Date().toISOString() })
      .where(eq(emailsTable.id, emailId.toString()));
  }

  @OnEvent(PipelineEvents.ProcessFailed)
  public async handleProcessFailed(event: ProcessFailedEvent) {
    const { emailId, error } = event;

    await this.db
      .update(emailsTable)
      .set({
        ingestionStatus: 'failed',
        ingestionLastError: error,
        ingestionLastAttemptAt: new Date().toISOString(),
        ingestionCompletedAt: new Date().toISOString(),
      })
      .where(eq(emailsTable.id, emailId));
  }

  // @OnEvent(PipelineEvents.FilteringCompleted)
  // public async handleFilteringCompleted(event: FilteringCompletedEvent) {
  //   const { userProfileId, emailId, shouldProcess } = event;

  //   if (!shouldProcess) {
  //     this.logger.debug({
  //       msg: 'Email filtered out, skipping processing',
  //       emailId: emailId.toString(),
  //     });
  //     await this.updateEmailStatus(emailId, 'completed');
  //     return;
  //   }

  //   // Queue for processing
  //   await this.amqpConnection.publish('email.pipeline', 'email.process', {
  //     userProfileId: userProfileId.toString(),
  //     emailId: emailId.toString(),
  //   });
  // }

  // @OnEvent(PipelineEvents.ProcessingCompleted)
  // public async handleProcessingCompleted(event: ProcessingCompletedEvent) {
  //   const { userProfileId, emailId, bodyProcessed } = event;

  //   if (!bodyProcessed) {
  //     // If no body was processed (e.g., empty email), mark as completed
  //     await this.updateEmailStatus(emailId, 'completed');
  //     return;
  //   }

  //   // Queue for chunking
  //   await this.amqpConnection.publish('email.pipeline', 'email.chunk', {
  //     userProfileId: userProfileId.toString(),
  //     emailId: emailId.toString(),
  //   });
  // }

  // @OnEvent(PipelineEvents.ChunkingCompleted)
  // public async handleChunkingCompleted(event: ChunkingCompletedEvent) {
  //   const { userProfileId, emailId, chunks } = event;

  //   if (!chunks.length) {
  //     this.logger.debug({
  //       msg: 'No chunks generated, completing pipeline',
  //       emailId: emailId.toString(),
  //     });
  //     await this.updateEmailStatus(emailId, 'completed');
  //     return;
  //   }

  //   // Queue for embedding
  //   await this.amqpConnection.publish('email.pipeline', 'email.embed', {
  //     userProfileId: userProfileId.toString(),
  //     emailId: emailId.toString(),
  //     chunks,
  //   });
  // }

  // @OnEvent(PipelineEvents.EmbeddingCompleted)
  // public async handleEmbeddingCompleted(event: EmbeddingCompletedEvent) {
  //   const { userProfileId, emailId, embeddings } = event;

  //   // Queue for indexing
  //   await this.amqpConnection.publish('email.pipeline', 'email.index', {
  //     userProfileId: userProfileId.toString(),
  //     emailId: emailId.toString(),
  //     embeddings,
  //   });
  // }

  // @OnEvent(PipelineEvents.IndexingCompleted)
  // public async handleIndexingCompleted(event: IngestCompletedEvent) {
  //   const { emailId } = event;
  //   await this.updateEmailStatus(emailId, 'completed');
  // }

  // private async updateEmailStatus(emailId: TypeID<'email'>, status: string) {
  //   await this.db
  //     .update(emailsTable)
  //     .set({
  //       ingestionStatus: status as any,
  //       ingestionCompletedAt: new Date().toISOString(),
  //     })
  //     .where(eq(emailsTable.id, emailId.toString()));
  // }
}
