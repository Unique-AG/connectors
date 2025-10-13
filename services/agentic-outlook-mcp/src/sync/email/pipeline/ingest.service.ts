import { createHash } from 'node:crypto';
import { AmqpConnection, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Attachment, Message } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { ConsumeMessage } from 'amqplib';
import { snakeCase } from 'lodash';
import { serializeError } from 'serialize-error-cjs';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, EmailInput } from '../../../drizzle';
import { normalizeError } from '../../../utils/normalize-error';
import { EmailService } from '../email.service';
import { EmailSyncService } from '../email-sync.service';
import { IngestCompletedEvent, PipelineEvents } from './pipeline.events';

const MAX_ATTEMPTS = 6;
const BASE_DELAY_MS = 60_000; // 1 minute
const MIN_DELAY_MS = 15_000; // clamp floor (optional)
const MAX_DELAY_MS = 30 * 60_000; // 30 minutes cap
const JITTER_RATIO = 0.2; // ±20%

function computeDelayMs(attempt: number) {
  const exp = 2 ** Math.max(0, attempt - 1);
  const base = Math.min(MAX_DELAY_MS, Math.max(MIN_DELAY_MS, BASE_DELAY_MS * exp));
  const jitter = 1 + (Math.random() * 2 - 1) * JITTER_RATIO; // 0.8..1.2 if 20%
  return Math.floor(base * jitter);
}

interface DeletedItem {
  id: string;
  '@removed'?: {
    reason: string;
  };
}

interface IngestMessage {
  message: Message;
  userProfileId: string;
  folderId: string;
}

@Injectable()
export class IngestService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly foldersMap = new Map<string, string>();

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly amqpConnection: AmqpConnection,
    private readonly emailService: EmailService,
    private readonly emailSyncService: EmailSyncService,
    private readonly eventEmitter: EventEmitter2,
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

    // This can cause data inconsistency if a folder is changed while ingesting.
    await this.ensureFoldersMap();

    if (attempt > 1) {
      this.logger.log({
        msg: 'Retrying ingest for message',
        messageId,
        attempt,
      });
    }

    try {
      const isDeleted = (message as unknown as DeletedItem)['@removed'] !== undefined;
      if (isDeleted) {
        await this.emailService.deleteEmails(TypeID.fromString(userProfileId, 'user_profile'), [
          messageId,
        ]);
        return;
      }

      let attachments: Attachment[] = [];
      if (message.hasAttachments)
        attachments = await this.emailSyncService.getAttachments(
          messageId,
          folderId,
          TypeID.fromString(userProfileId, 'user_profile'),
        );

      const mappedEmail = this.mapMessageToEmail({ message, attachments, userProfileId, folderId });
      mappedEmail.bodyTextFingerprint = mappedEmail.bodyText
        ? createHash('sha256').update(this.normalizeBody(mappedEmail.bodyText)).digest('hex')
        : null;
      mappedEmail.bodyHtmlFingerprint = mappedEmail.bodyHtml
        ? createHash('sha256').update(this.normalizeBody(mappedEmail.bodyHtml)).digest('hex')
        : null;

      mappedEmail.ingestionStatus = 'ingested';
      mappedEmail.ingestionLastAttemptAt = new Date().toISOString();

      const savedId = await this.emailService.upsertEmail(
        TypeID.fromString(userProfileId, 'user_profile'),
        folderId,
        mappedEmail,
      );

      this.eventEmitter.emit(
        PipelineEvents.IngestCompleted,
        new IngestCompletedEvent(
          TypeID.fromString(userProfileId, 'user_profile'),
          folderId,
          savedId,
        ),
      );

      return;
    } catch (error) {
      const serializedError = serializeError(normalizeError(error));
      this.logger.error({
        msg: 'INGEST failed.',
        message,
        attempt,
        error: serializedError,
      });

      if (attempt >= MAX_ATTEMPTS) {
        await this.amqpConnection.publish('email.pipeline.dlq', 'email.ingest.dlq', {
          ...message,
          __error: serializedError,
          __failedAt: new Date().toISOString(),
          __attempt: attempt,
        });
        await this.emailService.upsertEmail(
          TypeID.fromString(userProfileId, 'user_profile'),
          folderId,
          {
            messageId,
            userProfileId,
            folderId,
            ingestionStatus: 'failed',
            ingestionLastError: serializedError.message,
            ingestionLastAttemptAt: new Date().toISOString(),
            ingestionCompletedAt: new Date().toISOString(),
          },
        );
        return;
      }

      const delayMs = computeDelayMs(attempt);
      await this.amqpConnection.publish('email.pipeline.retry', 'email.ingest.retry', message, {
        expiration: String(delayMs),
        headers: { 'x-attempt': attempt + 1 },
      });

      return;
    }
  }

  private async ensureFoldersMap(): Promise<void> {
    if (this.foldersMap.size === 0) {
      const folders = await this.db.query.folders.findMany();
      folders.forEach((folder) => {
        this.foldersMap.set(folder.folderId, folder.name);
      });
    }
  }

  private normalizeBody(body: string): string {
    return body
      .normalize('NFKC')
      .replace(/\r\n/g, '\n')
      .replace(/[ \t]+/g, ' ')
      .trim();
  }

  private mapMessageToEmail({
    message,
    attachments,
    userProfileId,
    folderId,
  }: {
    message: Message;
    attachments: Attachment[];
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

      isRead: message.isRead || false,
      isDraft: message.isDraft || false,

      tags,

      hasAttachments: message.hasAttachments || false,
      attachments: attachments.map((attachment) => ({
        id: attachment.id,
        filename: attachment.name,
        mimeType: attachment.contentType,
        sizeBytes: attachment.size,
        isInline: attachment.isInline,
      })),
      attachmentCount: attachments.length,

      // These values must be updated in post-processing.
      sizeBytes: 0,
      headers: null,

      userProfileId,
      folderId,
    };
  }
}
