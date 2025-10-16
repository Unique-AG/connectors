import { RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Message } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { SpanStatusCode } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';
import { snakeCase } from 'lodash';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, EmailInput } from '../../../drizzle';
import { EmailService } from '../email.service';
import { DeletedItem } from '../email-sync.service';
import { IngestCompletedEvent, IngestFailedEvent, PipelineEvents } from '../pipeline.events';
import { PipelineRetryService } from '../pipeline-retry.service';
import { TracePropagationService } from '../trace-propagation.service';

interface IngestMessage {
  message: Message;
  userProfileId: string;
  folderId: string;
  emailId: string;
}

@Injectable()
export class IngestService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly foldersMap = new Map<string, string>();

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly emailService: EmailService,
    private readonly eventEmitter: EventEmitter2,
    private readonly pipelineRetryService: PipelineRetryService,
    private readonly tracePropagation: TracePropagationService,
  ) {}

  @RabbitSubscribe({
    exchange: 'email.pipeline',
    routingKey: 'email.ingest',
    queue: 'q.email.ingest',
  })
  public async ingest(ingestMessage: IngestMessage, amqpMessage: ConsumeMessage) {
    const { message, userProfileId, folderId } = ingestMessage;
    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);

    // biome-ignore lint/style/noNonNullAssertion: All messages always have an id. The MS type is faulty.
    const messageId = message.id!;

    return this.tracePropagation.withExtractedContext(
      amqpMessage,
      'email.pipeline.ingest',
      {
        'email.id': ingestMessage.emailId,
        'user.id': userProfileId,
        'folder.id': folderId,
        'pipeline.step': 'ingest',
        'attempt': attempt,
      },
      async (span) => {
        // This can cause data inconsistency if a folder is changed while ingesting.
        await this.ensureFoldersMap();

        if (attempt > 1) {
          this.logger.log({
            msg: 'Retrying ingest for message',
            messageId,
            attempt,
          });
          span.addEvent('retry', { attempt });
        }

        try {
          const isDeleted = (message as unknown as DeletedItem)['@removed'] !== undefined;
          if (isDeleted) {
            span.addEvent('email.deleted');
            await this.emailService.deleteEmails(TypeID.fromString(userProfileId, 'user_profile'), [
              messageId,
            ]);
            span.setStatus({ code: SpanStatusCode.OK });
            return;
          }

          const mappedEmail = this.mapMessageToEmail({ message, userProfileId, folderId });

          const savedId = await this.emailService.upsertEmail(
            TypeID.fromString(userProfileId, 'user_profile'),
            folderId,
            mappedEmail,
          );

          span.addEvent('email.saved', { 'email.id': savedId.toString() });
          span.setStatus({ code: SpanStatusCode.OK });

          const traceHeaders = this.tracePropagation.extractTraceHeaders(amqpMessage);
          this.eventEmitter.emit(
            PipelineEvents.IngestCompleted,
            new IngestCompletedEvent(
              TypeID.fromString(userProfileId, 'user_profile'),
              folderId,
              savedId,
              traceHeaders,
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
            message: ingestMessage,
            amqpMessage,
            error,
            retryExchange: 'email.pipeline.retry',
            retryRoutingKey: 'email.ingest.retry',
            failedEventName: PipelineEvents.IngestFailed,
            createFailedEvent: (serializedError) =>
              new IngestFailedEvent(
                TypeID.fromString(userProfileId, 'user_profile'),
                folderId,
                messageId,
                serializedError,
              ),
          });
          return;
        }
      },
    );
  }

  private async ensureFoldersMap(): Promise<void> {
    if (this.foldersMap.size === 0) {
      const folders = await this.db.query.folders.findMany();
      folders.forEach((folder) => {
        this.foldersMap.set(folder.folderId, folder.name);
      });
    }
  }

  private mapMessageToEmail({
    message,
    userProfileId,
    folderId,
  }: {
    message: Message;
    userProfileId: string;
    folderId: string;
  }): EmailInput {
    const tags: string[] = [];

    if (message.importance) tags.push(`importance:${snakeCase(message.importance)}`);

    if (message.parentFolderId && this.foldersMap?.get(message.parentFolderId))
      tags.push(`folder:${snakeCase(this.foldersMap.get(message.parentFolderId))}`);

    return {
      // biome-ignore lint/style/noNonNullAssertion: All messages always have an id. The MS type is faulty.
      messageId: message.id!,
      conversationId: message.conversationId,
      internetMessageId: message.internetMessageId,
      webLink: message.webLink,
      version: message.changeKey,

      from: message.from
        ? {
            name: message.from.emailAddress?.name || null,
            address: message.from.emailAddress?.address || '',
          }
        : null,
      sender: message.sender
        ? {
            name: message.sender.emailAddress?.name || null,
            address: message.sender.emailAddress?.address || '',
          }
        : null,
      replyTo: message.replyTo?.map((r) => ({
        name: r.emailAddress?.name || null,
        address: r.emailAddress?.address || '',
      })),
      to:
        message.toRecipients?.map((r) => ({
          name: r.emailAddress?.name || null,
          address: r.emailAddress?.address || '',
        })) || [],
      cc:
        message.ccRecipients?.map((r) => ({
          name: r.emailAddress?.name || null,
          address: r.emailAddress?.address || '',
        })) || [],
      bcc:
        message.bccRecipients?.map((r) => ({
          name: r.emailAddress?.name || null,
          address: r.emailAddress?.address || '',
        })) || [],

      sentAt: message.sentDateTime,
      receivedAt: message.receivedDateTime,

      subject: message.subject,
      preview: message.bodyPreview,
      bodyText: message.body?.contentType === 'text' ? message.body?.content : null,
      bodyHtml: message.body?.contentType === 'html' ? message.body?.content : null,

      uniqueBodyText:
        message.uniqueBody?.contentType === 'text' ? message.uniqueBody?.content : null,
      uniqueBodyHtml:
        message.uniqueBody?.contentType === 'html' ? message.uniqueBody?.content : null,

      isRead: message.isRead || false,
      isDraft: message.isDraft || false,

      tags,

      hasAttachments: message.hasAttachments || false,
      attachments: message.attachments?.map((attachment) => ({
        id: attachment.id,
        filename: attachment.name,
        mimeType: attachment.contentType,
        sizeBytes: attachment.size,
        isInline: attachment.isInline,
      })),
      attachmentCount: message.attachments?.length || 0,

      headers: message.internetMessageHeaders?.map((header) => ({
        // biome-ignore lint/style/noNonNullAssertion: MS Graph does not send headers without a name.
        name: header.name!,
        value: header.value,
      })),

      // These values must be updated in post-processing.
      sizeBytes: 0,

      userProfileId,
      folderId,
    };
  }
}
