import { AmqpConnection, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { RecursiveCharacterTextSplitter } from '@langchain/textsplitters';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';
import { and, eq } from 'drizzle-orm';
import { encodingForModel } from 'js-tiktoken';
import {
  DRIZZLE,
  DrizzleDatabase,
  Email,
  emails as emailsTable,
  Point,
  PointInput,
  points as pointsTable,
} from '../../../drizzle';
import { LLMService } from '../../../llm/llm.service';
import { addSpanEvent } from '../../../utils/add-span-event';
import { OrchestratorEventType } from '../orchestrator.messages';
import { FatalPipelineError } from '../pipeline.errors';
import { RetryService } from '../retry.service';
import { TracePropagationService } from '../trace-propagation.service';
import { PipelineStageBase, PipelineStageConfig } from './pipeline-stage.base';

interface EmbedMessage {
  userProfileId: string;
  emailId: string;
}

const CHUNK_SIZE = 3_200;
const MAX_TOKENS = 32_000;

@Injectable()
export class EmbedService extends PipelineStageBase<EmbedMessage> {
  protected readonly logger = new Logger(this.constructor.name);
  protected readonly config: PipelineStageConfig = {
    spanName: 'email.pipeline.embed',
    retryRoutingKey: 'email.embed.retry',
    successEvent: OrchestratorEventType.EmbeddingCompleted,
    failureEvent: OrchestratorEventType.EmbeddingFailed,
  };

  public constructor(
    amqpConnection: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    retryService: RetryService,
    tracePropagation: TracePropagationService,
    private readonly llmService: LLMService,
  ) {
    super(amqpConnection, retryService, tracePropagation);
  }

  @RabbitSubscribe({
    exchange: 'email.pipeline',
    routingKey: 'email.embed',
    queue: 'q.email.embed',
  })
  public async embed(message: EmbedMessage, amqpMessage: ConsumeMessage) {
    return this.executeStage(message, amqpMessage, {
      'email.id': message.emailId,
      'user.id': message.userProfileId,
      'pipeline.step': 'embed',
    });
  }

  protected getMessageIdentifiers(message: EmbedMessage) {
    return {
      userProfileId: message.userProfileId,
      emailId: message.emailId,
    };
  }

  protected buildSuccessPayload(message: EmbedMessage, _additionalData?: unknown) {
    return {
      userProfileId: message.userProfileId,
      emailId: message.emailId,
    };
  }

  protected buildFailurePayload(message: EmbedMessage, _error: string) {
    return {
      userProfileId: message.userProfileId,
      emailId: message.emailId,
    };
  }

  protected async processMessage(
    message: EmbedMessage,
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
      this.logger.warn('Email not found, skipping embed');
      addSpanEvent(span, 'email.not_found', { emailId, userProfileId });
      return;
    }

    if (email.points.length > 0) {
      this.logger.warn('Email already has vectors, skipping embed');
      addSpanEvent(span, 'email.already_has_vectors', { emailId, userProfileId });
      return;
    }

    if (!email.processedBody) throw new FatalPipelineError('Email processed body is missing');
    const chunks = await this.createChunks(email.processedBody);
    const vectors = await this.createVectors(email, chunks, { span });

    this.logger.debug({
      msg: 'Generated embeddings',
      vectorsCreated: vectors.length,
    });
  }

  private async createChunks(body: string): Promise<string[]> {
    if (body.length < 5000) return [body];

    const splitter = new RecursiveCharacterTextSplitter({
      chunkSize: CHUNK_SIZE,
      chunkOverlap: 0,
    });

    return splitter.splitText(body);
  }

  private countTokens(text: string): number {
    const enc = encodingForModel('gpt-4-turbo');
    const tokens = enc.encode(text);
    return tokens.length;
  }

  private async createVectors(
    email: Email,
    chunks: string[],
    options: { span: Span },
  ): Promise<Point[]> {
    const pointInputs: PointInput[] = [];
    const documents = [];

    // We do not prefix or add the subject to the chunks as we have other vectors that will include the subject.
    // We're trying to not duplicate information in the vectors to avoid an overweight.
    // We will ingest multiple points per email, each with a different point type.
    // 1. Either the summarized body or the full email body with the subject
    // 2. If we chunked the email, we will ingest one point per chunk.
    if (email.summarizedBody) {
      documents.push([`Subject: ${email.subject}\n\nSummary: ${email.summarizedBody}`]);
      pointInputs.push({
        emailId: email.id,
        pointType: 'summary',
        vector: [],
        index: 0,
      });
    } else {
      const content = `Subject: ${email.subject}\n\nBody: ${email.processedBody}`;
      if (this.countTokens(content) >= MAX_TOKENS - 50)
        throw new FatalPipelineError('Processed body is too long. Should have summarized');
      documents.push([content]);
      pointInputs.push({
        emailId: email.id,
        pointType: 'full',
        vector: [],
        index: 0,
      });
    }

    if (chunks.length > 1) {
      documents.push(chunks);
      for (let index = 0; index < chunks.length; index++) {
        pointInputs.push({
          emailId: email.id,
          pointType: 'chunk',
          vector: [],
          index,
        });
      }
    }

    if (documents.length === 0) {
      this.logger.warn({
        msg: 'Email has no documents to embed, skipping',
        emailId: email.id,
        userProfileId: email.userProfileId,
      });
      addSpanEvent(options.span, 'email.no_documents_to_embed', {
        emailId: email.id,
        userProfileId: email.userProfileId,
      });
      return [];
    }

    const embeddedDocuments = await this.llmService.contextualizedEmbed(documents);
    const fullOrSummaryVector = embeddedDocuments[0];
    if (!fullOrSummaryVector || !fullOrSummaryVector[0]) {
      throw new Error('Failed to get full or summary vector');
    }
    // biome-ignore lint/style/noNonNullAssertion: We know that pointInput exists.
    pointInputs[0]!.vector = fullOrSummaryVector[0];

    if (chunks.length > 1) {
      const chunkVectors = embeddedDocuments[1];
      if (chunkVectors) {
        for (let i = 0; i < chunkVectors.length; i++) {
          const vector = chunkVectors[i];
          if (!vector) continue;
          // Map to correct position in pointInputs: position 0 is summary/full, chunks start at position 1
          // biome-ignore lint/style/noNonNullAssertion: We know that pointInput exists.
          pointInputs[1 + i]!.vector = vector;
        }
      }
    }

    return this.db.insert(pointsTable).values(pointInputs).returning();
  }
}
