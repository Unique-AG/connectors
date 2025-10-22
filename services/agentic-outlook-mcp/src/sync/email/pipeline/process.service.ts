import { AmqpConnection, RabbitSubscribe } from "@golevelup/nestjs-rabbitmq";
import { startObservation } from "@langfuse/tracing";
import { Inject, Injectable, Logger } from "@nestjs/common";
import { Span, SpanStatusCode } from "@opentelemetry/api";
import { ConsumeMessage } from "amqplib";
import { and, asc, eq } from "drizzle-orm";
import {
  DRIZZLE,
  DrizzleDatabase,
  Email,
  emails as emailsTable,
} from "../../../drizzle";
import { addSpanEvent } from "../../../utils/add-span-event";
import { LLMEmailCleanupService } from "../lib/llm-email-cleanup/llm-email-cleanup.service";
import { LLMSummarizationService } from "../lib/llm-summarization-service/llm-summarization.service";
import { OrchestratorEventType } from "../orchestrator.messages";
import { RetryService } from "../retry.service";
import { TracePropagationService } from "../trace-propagation.service";

interface ProcessMessage {
  userProfileId: string;
  emailId: string;
}

interface ProcessMetadata {
  span: Span;
  emailId: string;
  userProfileId: string;
}

const SUMMARIZATION_THRESHOLD_CHARS = 1_600;

@Injectable()
export class ProcessService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly amqpConnection: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly retryService: RetryService,
    private readonly llmEmailCleanupService: LLMEmailCleanupService,
    private readonly llmSummarizationService: LLMSummarizationService,
    private readonly tracePropagation: TracePropagationService
  ) {}

  @RabbitSubscribe({
    exchange: "email.pipeline",
    routingKey: "email.process",
    queue: "q.email.process",
  })
  public async process(
    processMessage: ProcessMessage,
    amqpMessage: ConsumeMessage
  ) {
    const { userProfileId, emailId } = processMessage;
    const attempt = Number(amqpMessage.properties.headers?.["x-attempt"] ?? 1);

    return this.tracePropagation.withExtractedContext(
      amqpMessage,
      "email.pipeline.process",
      {
        "email.id": emailId,
        "user.id": userProfileId,
        "pipeline.step": "process",
        attempt: attempt,
      },
      async (span) => {
        if (attempt > 1) {
          this.logger.log({
            msg: "Retrying process for email",
            emailId,
            attempt,
          });
          addSpanEvent(span, "retry", { attempt });
        }

        try {
          const email = await this.db.query.emails.findFirst({
            where: and(
              eq(emailsTable.id, emailId),
              eq(emailsTable.userProfileId, userProfileId)
            ),
          });

          if (!email) {
            this.logger.warn("Email not found, skipping processing");
            addSpanEvent(span, "email.not_found", { emailId, userProfileId });
            span.setStatus({ code: SpanStatusCode.OK });
            return;
          }

          const { processedBody, language } = await this.cleanupBody(email, {
            span,
            emailId,
            userProfileId,
          });
          const summarizedBody = await this.summarizeBody(
            email,
            processedBody,
            {
              span,
              emailId,
              userProfileId,
            }
          );
          const threadSummary = await this.summarizeThread(email, {
            span,
            emailId,
            userProfileId,
          });

          this.logger.debug({
            msg: "Email processed",
            emailId: emailId,
            userProfileId: userProfileId,
          });

          addSpanEvent(
            span,
            "email.processed",
            { emailId, userProfileId },
            { language },
            {
              input: { body: email.uniqueBodyHtml },
              output: {
                language,
                processedBody,
                summarizedBody,
                threadSummary,
              },
            },
          );
          span.setStatus({ code: SpanStatusCode.OK });

          const traceHeaders =
            this.tracePropagation.extractTraceHeaders(amqpMessage);
          await this.amqpConnection.publish(
            "email.orchestrator",
            "orchestrator",
            {
              eventType: OrchestratorEventType.ProcessingCompleted,
              userProfileId,
              emailId,
              timestamp: new Date().toISOString(),
            },
            { headers: traceHeaders }
          );

          return;
        } catch (error) {
          span.setStatus({
            code: SpanStatusCode.ERROR,
            message: error instanceof Error ? error.message : String(error),
          });
          span.recordException(error as Error);
          startObservation(
            "error",
            {
              statusMessage:
                error instanceof Error ? error.message : String(error),
              level: "ERROR",
            },
            { asType: "event", parentSpanContext: span.spanContext() }
          ).end();
          await this.retryService.handleError({
            message: processMessage,
            amqpMessage,
            error,
            retryExchange: "email.pipeline.retry",
            retryRoutingKey: "email.process.retry",
            onMaxRetriesExceeded: async (_msg, errorStr, traceHeaders) => {
              await this.amqpConnection.publish(
                "email.orchestrator",
                "orchestrator",
                {
                  eventType: OrchestratorEventType.ProcessingFailed,
                  userProfileId,
                  emailId,
                  timestamp: new Date().toISOString(),
                  error: errorStr,
                },
                { headers: traceHeaders }
              );
            },
          });
          return;
        }
      }
    );
  }

  private async cleanupBody(
    email: Email,
    options: ProcessMetadata
  ): Promise<{
    processedBody: string;
    language: string;
  }> {
    if (email.processedBody && email.language) {
      this.logger.log({
        msg: "Email body already cleaned, skipping",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      addSpanEvent(options.span, "email.body_already_cleaned", {
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return { processedBody: email.processedBody, language: email.language };
    }

    const {
      cleanMarkdown,
      meta: { language },
    } = await this.llmEmailCleanupService.cleanupEmail(email);

    await this.db
      .update(emailsTable)
      .set({
        processedBody: cleanMarkdown,
        language,
      })
      .where(
        and(
          eq(emailsTable.id, options.emailId),
          eq(emailsTable.userProfileId, options.userProfileId)
        )
      );
    return { processedBody: cleanMarkdown, language };
  }

  private async summarizeBody(
    email: Email,
    processedBody: string,
    options: ProcessMetadata
  ): Promise<string> {
    if (email.summarizedBody) {
      this.logger.log({
        msg: "Email already summarized, skipping",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      addSpanEvent(options.span, "email.already_summarized", {
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return email.summarizedBody;
    }

    if (processedBody.length < SUMMARIZATION_THRESHOLD_CHARS) {
      this.logger.log({
        msg: "Processed body is too short, skipping summarization",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      addSpanEvent(options.span, "email.processed_body_too_short", {
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return processedBody;
    }

    const summarization = await this.llmSummarizationService.summarize(
      processedBody
    );

    await this.db
      .update(emailsTable)
      .set({
        summarizedBody: summarization.summarizedBody,
      })
      .where(
        and(
          eq(emailsTable.id, options.emailId),
          eq(emailsTable.userProfileId, options.userProfileId)
        )
      );

    return summarization.summarizedBody;
  }

  private async summarizeThread(
    email: Email,
    options: ProcessMetadata
  ): Promise<string | undefined> {
    if (email.threadSummary) {
      this.logger.log({
        msg: "Thread already summarized, skipping",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      addSpanEvent(options.span, "thread.already_summarized", {
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return email.threadSummary;
    }

    if (!email.conversationId) {
      this.logger.log({
        msg: "Email has no conversation ID, skipping thread summarization",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      addSpanEvent(options.span, "email.no_conversation_id", {
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return;
    }

    const thread = await this.db.query.emails.findMany({
      where: and(
        eq(emailsTable.conversationId, email.conversationId),
        eq(emailsTable.userProfileId, email.userProfileId)
      ),
      orderBy: [asc(emailsTable.receivedAt)],
    });

    if (thread.length <= 1) {
      this.logger.log({
        msg: "Thread has only one email, skipping thread summarization",
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      addSpanEvent(options.span, "thread.only_one_email", {
        emailId: options.emailId,
        userProfileId: options.userProfileId,
      });
      return;
    }

    const threadText = thread.map((email) => email.processedBody).join("\n");
    const threadSummary = await this.llmSummarizationService.summarize(
      threadText
    );

    await this.db
      .update(emailsTable)
      .set({
        threadSummary: threadSummary.summarizedBody,
      })
      .where(
        and(
          eq(emailsTable.id, options.emailId),
          eq(emailsTable.userProfileId, options.userProfileId)
        )
      );
    return threadSummary.summarizedBody;
  }
}
