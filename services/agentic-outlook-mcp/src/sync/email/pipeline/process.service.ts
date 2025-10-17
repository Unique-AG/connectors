import { RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Readability } from '@mozilla/readability';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { SpanStatusCode } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';
import DOMPurify from 'dompurify';
import { and, eq } from 'drizzle-orm';
import EmailReplyParser from 'email-reply-parser';
import { JSDOM } from 'jsdom';
import Turndown from 'turndown';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, Email, emails as emailsTable } from '../../../drizzle';
import { LLMEmailCleanupService } from '../lib/llm-email-cleanup/llm-email-cleanup.service';
import { PipelineEvents, ProcessFailedEvent, ProcessingCompletedEvent } from '../pipeline.events';
import { PipelineRetryService } from '../pipeline-retry.service';
import { TracePropagationService } from '../trace-propagation.service';

interface ProcessMessage {
  userProfileId: string;
  emailId: string;
}

@Injectable()
export class ProcessService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly eventEmitter: EventEmitter2,
    private readonly pipelineRetryService: PipelineRetryService,
    private readonly llmEmailCleanupService: LLMEmailCleanupService,
    private readonly tracePropagation: TracePropagationService,
  ) {}

  @RabbitSubscribe({
    exchange: 'email.pipeline',
    routingKey: 'email.process',
    queue: 'q.email.process',
  })
  public async process(processMessage: ProcessMessage, amqpMessage: ConsumeMessage) {
    const { userProfileId, emailId } = processMessage;
    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);

    return this.tracePropagation.withExtractedContext(
      amqpMessage,
      'email.pipeline.process',
      {
        'email.id': emailId,
        'user.id': userProfileId,
        'pipeline.step': 'process',
        attempt: attempt,
      },
      async (span) => {
        if (attempt > 1) {
          this.logger.log({
            msg: 'Retrying process for email',
            emailId,
            attempt,
          });
          span.addEvent('retry', { attempt });
        }

        try {
          const email = await this.db.query.emails.findFirst({
            where: and(eq(emailsTable.id, emailId), eq(emailsTable.userProfileId, userProfileId)),
          });

          if (!email) {
            this.logger.warn('Email not found, skipping processing');
            span.addEvent('email.not_found');
            span.setStatus({ code: SpanStatusCode.OK });
            return;
          }

          if (email.processedBody && email.language) {
            this.logger.log({
              msg: 'Email already processed, skipping',
              emailId,
              userProfileId,
            });
            span.addEvent('email.already_processed');
            span.setStatus({ code: SpanStatusCode.OK });
            return;
          }

          const {
            cleanMarkdown,
            meta: { language },
          } = await this.llmEmailCleanupService.cleanupEmail(email);

          span.addEvent('email.cleaned', { language });

          await this.db
            .update(emailsTable)
            .set({
              processedBody: cleanMarkdown,
              language,
            })
            .where(and(eq(emailsTable.id, emailId), eq(emailsTable.userProfileId, userProfileId)));

          this.logger.debug({
            msg: 'Email processed',
            emailId: emailId,
            userProfileId: userProfileId,
          });

          span.addEvent('email.processed', { language });
          span.setStatus({ code: SpanStatusCode.OK });

          this.eventEmitter.emit(
            PipelineEvents.ProcessingCompleted,
            new ProcessingCompletedEvent(
              TypeID.fromString(userProfileId, 'user_profile'),
              TypeID.fromString(emailId, 'email'),
            ),
          );

          return;
        } catch (error) {
          span.setStatus({
            code: SpanStatusCode.ERROR,
            message: error instanceof Error ? error.message : String(error),
          });
          span.recordException(error as Error);
          await this.pipelineRetryService.handlePipelineError({
            message: processMessage,
            amqpMessage,
            error,
            retryExchange: 'email.pipeline.retry',
            retryRoutingKey: 'email.process.retry',
            failedEventName: PipelineEvents.ProcessFailed,
            createFailedEvent: (serializedError) =>
              new ProcessFailedEvent(
                TypeID.fromString(userProfileId, 'user_profile'),
                emailId,
                serializedError,
              ),
          });
          return;
        }
      },
    );
  }

  // biome-ignore lint/correctness/noUnusedPrivateClassMembers: Currently unused in favor of LLM email cleanup.
  private async purifyBody(email: Email) {
    const { uniqueBodyText, uniqueBodyHtml } = email;

    let cleanHtml: string | null = null;
    let cleanText: string | null = null;

    if (uniqueBodyText) {
      cleanText = uniqueBodyText;
    }

    if (uniqueBodyHtml) {
      const window = new JSDOM('').window;
      const purify = DOMPurify(window);
      const clean = purify.sanitize(uniqueBodyHtml);

      const emailReplyParser = new EmailReplyParser();
      const parsed = emailReplyParser.read(clean);

      const docClean = new JSDOM(parsed.getVisibleText()).window.document;
      const article = new Readability(docClean).parse();
      if (!article || !article.content) return;

      const turndown = new Turndown();
      cleanHtml = turndown.turndown(article.content);
    }

    return {
      cleanHtml,
      cleanText,
    };
  }
}
