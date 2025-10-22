import { AmqpConnection, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { RecursiveCharacterTextSplitter } from '@langchain/textsplitters';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';
import { and, eq } from 'drizzle-orm';
import { encodingForModel } from 'js-tiktoken';
import { DRIZZLE, DrizzleDatabase, Email, emails as emailsTable, Vector, VectorInput } from '../../../drizzle';
import { vectors as vectorsTable } from '../../../drizzle/schema/sync/vectors.table';
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
    return this.executeStage(
      message,
      amqpMessage,
      {
        'email.id': message.emailId,
        'user.id': message.userProfileId,
        'pipeline.step': 'embed',
      },
    );
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
        vectors: true,
      },
    });

    if (!email) {
      this.logger.warn('Email not found, skipping embed');
      addSpanEvent(span, 'email.not_found', { emailId, userProfileId });
      return;
    }

    if (!email.processedBody) throw new FatalPipelineError('Email processed body is missing');
    const chunks = await this.createChunks(email.processedBody);

    if (email.vectors.length > 0) {
      this.logger.warn('Email already has vectors, skipping embed');
      addSpanEvent(span, 'email.already_has_vectors', { emailId, userProfileId });
    }

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
  ): Promise<Vector[]> {
    const vectorInputs: VectorInput[] = [];
    const documents = [];
    const documentNames = [];

    // We do not prefix or add the subject to the chunks as we have other vectors that will include the subject.
    // We're trying to not duplicate information in the vectors to avoid an overweight.
    // In total we create up to 3 vectors per email:
    // 1. The chunks vector
    // 2. The summarized body vector
    // 3. The processed body vector
    if (chunks.length > 1) {
      documents.push(chunks);
      documentNames.push('chunks');
    }
    if (email.summarizedBody) {
      documents.push([`Subject: ${email.subject}\n\nSummary: ${email.summarizedBody}`]);
      documentNames.push('summary');
    }
    if (email.processedBody && this.countTokens(email.processedBody) < MAX_TOKENS) {
      documents.push([`Subject: ${email.subject}\n\nBody: ${email.processedBody}`]);
      documentNames.push('full');
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
    
    for (let index = 0; index < embeddedDocuments.length; index++) {
      const embeddedDocument = embeddedDocuments[index];
      if (!embeddedDocument || !embeddedDocument[0]) continue;
      const name = documentNames[index];
      const dimension = embeddedDocument[0].length;

      vectorInputs.push({
        emailId: email.id,
        // biome-ignore lint/style/noNonNullAssertion: Unnecessary typescript check
        name: name!,
        dimension,
        embeddings: embeddedDocument,
      });
    }

    return this.db.insert(vectorsTable).values(vectorInputs).returning();
  }
}
