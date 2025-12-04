import { AmqpConnection, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from '@opentelemetry/api';
import { components } from '@qdrant/js-client-rest/dist/types/openapi/generated_schema';
import { ConsumeMessage } from 'amqplib';
import dayjs from 'dayjs';
import { and, eq } from 'drizzle-orm';
import { addressToString, DRIZZLE, DrizzleDatabase, emails as emailsTable } from '../../../drizzle';
import { QdrantService } from '../../../qdrant/qdrant.service';
import { addSpanEvent } from '../../../utils/add-span-event';
import { OrchestratorEventType } from '../orchestrator.messages';
import { RetryService } from '../retry.service';
import { TracePropagationService } from '../trace-propagation.service';
import { PipelineStageBase, PipelineStageConfig } from './pipeline-stage.base';

interface IndexMessage {
  userProfileId: string;
  emailId: string;
}

@Injectable()
export class IndexService extends PipelineStageBase<IndexMessage> {
  protected readonly logger = new Logger(this.constructor.name);
  protected readonly config: PipelineStageConfig = {
    spanName: 'email.pipeline.index',
    retryRoutingKey: 'email.index.retry',
    successEvent: OrchestratorEventType.IndexingCompleted,
    failureEvent: OrchestratorEventType.IndexingFailed,
  };

  public constructor(
    amqpConnection: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    retryService: RetryService,
    tracePropagation: TracePropagationService,
    private readonly qdrantService: QdrantService,
  ) {
    super(amqpConnection, retryService, tracePropagation);
  }

  @RabbitSubscribe({
    exchange: 'email.pipeline',
    routingKey: 'email.index',
    queue: 'q.email.index',
  })
  public async index(message: IndexMessage, amqpMessage: ConsumeMessage) {
    return this.executeStage(message, amqpMessage, {
      'email.id': message.emailId,
      'user.id': message.userProfileId,
      'pipeline.step': 'index',
    });
  }

  protected getMessageIdentifiers(message: IndexMessage) {
    return {
      userProfileId: message.userProfileId,
      emailId: message.emailId,
    };
  }

  protected buildSuccessPayload(message: IndexMessage, _additionalData?: unknown) {
    return {
      userProfileId: message.userProfileId,
      emailId: message.emailId,
    };
  }

  protected buildFailurePayload(message: IndexMessage, _error: string) {
    return {
      userProfileId: message.userProfileId,
      emailId: message.emailId,
    };
  }

  protected async processMessage(
    message: IndexMessage,
    _amqpMessage: ConsumeMessage,
    span: Span,
  ): Promise<void> {
    const { userProfileId, emailId } = message;

    const email = await this.db.query.emails.findFirst({
      where: and(eq(emailsTable.id, emailId), eq(emailsTable.userProfileId, userProfileId)),
      with: {
        points: true,
      },
    });

    if (!email) {
      this.logger.warn('Email not found, skipping index');
      addSpanEvent(span, 'email.not_found', { emailId, userProfileId });
      return;
    }

    if (email.points.length === 0) {
      this.logger.warn('Email has no vectors, skipping index');
      addSpanEvent(span, 'email.no_vectors', { emailId, userProfileId });
      return;
    }

    const collection = await this.qdrantService.ensureCollection({
      name: 'emails',
      vectors: {
        content: {
          size: 1024,
          distance: 'Cosine',
        },
      },
    });

    addSpanEvent(span, 'collection.ensured', { emailId, userProfileId }, undefined, {
      collectionName: 'emails',
      configuredVectors: collection.config.params.vectors,
    });

    const points: components['schemas']['PointStruct'][] = [];
    const chunkTotal = email.points.filter((p) => p.pointType === 'chunk').length;
    const metadata = {
      user_profile_id: userProfileId,
      email_id: emailId,
      subject: email.subject,
      language: email.language,
      attachment_count: email.attachmentCount,
      attachments: email.attachments?.map((a) => a.filename).join(','),
      tags: email.tags?.join(','),
      from: addressToString(email.from),
      to: email.to?.map(addressToString).join(','),
      cc: email.cc?.map(addressToString).join(','),
      bcc: email.bcc?.map(addressToString).join(','),
      sent_at: dayjs(email.sentAt).unix(),
      received_at: dayjs(email.receivedAt).unix(),
    };

    for (const point of email.points) {
      const payload =
        point.pointType === 'chunk'
          ? {
              ...metadata,
              point_type: 'chunk',
              chunk_index: point.index,
              chunk_total: chunkTotal,
            }
          : {
              ...metadata,
              point_type: point.pointType,
            };

      const pointStruct = {
        id: point.qdrantId.toString(),
        vector: {
          content: point.vector,
        },
        payload,
      };
      points.push(pointStruct);
    }

    await this.qdrantService.upsert('emails', points);

    addSpanEvent(span, 'email.indexed', {
      emailId,
      userProfileId,
      pointCount: points.length,
    });
  }
}
