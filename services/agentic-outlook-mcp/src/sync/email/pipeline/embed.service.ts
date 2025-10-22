import { AmqpConnection, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { RecursiveCharacterTextSplitter } from '@langchain/textsplitters';
import { startObservation } from '@langfuse/tracing';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span, SpanStatusCode } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';
import { and, eq } from 'drizzle-orm';
import { encodingForModel } from 'js-tiktoken';
import { DRIZZLE, DrizzleDatabase, Email, emails as emailsTable, Vector, VectorInput } from '../../../drizzle';
import { vectors as vectorsTable } from '../../../drizzle/schema/sync/vectors.table';
import { LLMService } from '../../../llm/llm.service';
import { OrchestratorEventType } from '../orchestrator.messages';
import { FatalPipelineError } from '../pipeline.errors';
import { RetryService } from '../retry.service';
import { TracePropagationService } from '../trace-propagation.service';

interface EmbedMessage {
  userProfileId: string;
  emailId: string;
}

const CHUNK_SIZE = 3_200;
const MAX_TOKENS = 32_000;

@Injectable()
export class EmbedService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly amqpConnection: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly retryService: RetryService,
    private readonly tracePropagation: TracePropagationService,
    private readonly llmService: LLMService,
  ) {}

  @RabbitSubscribe({
    exchange: 'email.pipeline',
    routingKey: 'email.embed',
    queue: 'q.email.embed',
  })
  public async chunking(message: EmbedMessage, amqpMessage: ConsumeMessage) {
    const { userProfileId, emailId } = message;
    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);

    return this.tracePropagation.withExtractedContext(
      amqpMessage,
      'email.pipeline.embed',
      {
        'email.id': emailId,
        'user.id': userProfileId,
        'pipeline.step': 'embed',
        attempt: attempt,
      },
      async (span) => {
        if (attempt > 1) {
          this.logger.log({
            msg: 'Retrying embed for email',
            emailId,
            attempt,
          });
          span.addEvent('retry', { attempt });
          startObservation(
            'retry',
            { metadata: { attempt } },
            { asType: 'event', parentSpanContext: span.spanContext() },
          ).end();
        }

        try {
          const email = await this.db.query.emails.findFirst({
            where: and(eq(emailsTable.id, emailId), eq(emailsTable.userProfileId, userProfileId)),
            with: {
              vectors: true,
            },
          });

          if (!email) {
            this.logger.warn('Email not found, skipping embed');
            span.addEvent('email.not_found');
            startObservation(
              'email.not_found',
              { metadata: { emailId, userProfileId } },
              { asType: 'event', parentSpanContext: span.spanContext() },
            ).end();
            span.setStatus({ code: SpanStatusCode.OK });
            return;
          }

          if (!email.processedBody) throw new FatalPipelineError('Email processed body is missing');
          const chunks = await this.createChunks(email.processedBody);

          if (email.vectors.length > 0) {
            this.logger.warn('Email already has vectors, skipping embed');
            span.addEvent('email.already_has_vectors');
            startObservation(
              'email.already_has_vectors',
              { metadata: { emailId, userProfileId } },
              { asType: 'event', parentSpanContext: span.spanContext() },
            ).end();
          }

          const vectors = await this.createVectors(email, chunks, { span });

          this.logger.debug({
            msg: 'Generated embeddings',
            vectorsCreated: vectors.length,
          });

          span.setStatus({ code: SpanStatusCode.OK });

          await this.amqpConnection.publish(
            'email.orchestrator',
            'orchestrator',
            {
              eventType: OrchestratorEventType.EmbeddingCompleted,
              userProfileId,
              emailId,
            },
            { headers: this.tracePropagation.extractTraceHeaders(amqpMessage) },
          );

          return;
        } catch (error) {
          span.setStatus({
            code: SpanStatusCode.ERROR,
            message: error instanceof Error ? error.message : String(error),
          });
          span.recordException(error as Error);
          startObservation(
            'error',
            {
              statusMessage: error instanceof Error ? error.message : String(error),
              level: 'ERROR',
            },
            { asType: 'event', parentSpanContext: span.spanContext() },
          ).end();
          await this.retryService.handleError({
            message,
            amqpMessage,
            error,
            retryExchange: 'email.pipeline.retry',
            retryRoutingKey: 'email.embed.retry',
            onMaxRetriesExceeded: async (_msg, errorStr, traceHeaders) => {
              await this.amqpConnection.publish(
                'email.orchestrator',
                'orchestrator',
                {
                  eventType: OrchestratorEventType.EmbeddingFailed,
                  userProfileId,
                  emailId,
                  timestamp: new Date().toISOString(),
                  error: errorStr,
                },
                { headers: traceHeaders },
              );
            },
          });
          return;
        }
      },
    );
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
      options.span.addEvent('email.no_documents_to_embed');
      startObservation(
        'email.no_documents_to_embed',
        { metadata: { emailId: email.id, userProfileId: email.userProfileId } },
        { asType: 'event', parentSpanContext: options.span.spanContext() },
      ).end();
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
