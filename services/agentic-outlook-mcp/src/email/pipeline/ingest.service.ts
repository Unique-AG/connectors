import { AmqpConnection, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Message } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConsumeMessage } from 'amqplib';
import { serializeError } from 'serialize-error-cjs';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, EmailInput } from '../../drizzle';
import { normalizeError } from '../../utils/normalize-error';
import { EmailService } from '../email.service';

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
  ) {}

  @RabbitSubscribe({
    exchange: 'email.pipeline',
    routingKey: 'email.ingest',
    queue: 'q.email.ingest',
  })
  public async ingest(ingestMessage: IngestMessage, amqpMessage: ConsumeMessage) {
    const { message, userProfileId, folderId } = ingestMessage;
    const attempt = Number(amqpMessage.properties.headers?.['x-attempt'] ?? 1);

    await this.ensureFoldersMap();

    this.logger.log({
      msg: 'Ingesting message',
      message,
      attempt,
    });

    try {
      const isDeleted = (message as unknown as DeletedItem)['@removed'] !== undefined;
      if (isDeleted) {
        await this.emailService.deleteEmails(TypeID.fromString(userProfileId, 'user_profile'), [
          // biome-ignore lint/style/noNonNullAssertion: Microsoft Graph API returns deleted items with an id
          message.id!,
        ]);
        return;
      }

      const mappedEmail = this.mapMessageToEmail(message, userProfileId, folderId, this.foldersMap);
      await this.emailService.upsertEmails(
        TypeID.fromString(userProfileId, 'user_profile'),
        folderId,
        [mappedEmail],
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

  private mapMessageToEmail(
    message: Message,
    userProfileId: string,
    folderId: string,
    foldersMap?: Map<string, string>,
  ): EmailInput {
    return {
      // biome-ignore lint/style/noNonNullAssertion: Microsoft Graph API returns emails with an id
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

      tags: [
        `importance:${message.importance}`,
        `${foldersMap?.get(message.parentFolderId || '') || null}`,
      ].filter(Boolean),

      hasAttachments: message.hasAttachments || false,

      // These values must be updated in post-processing.
      sizeBytes: 0,
      attachments: [],
      attachmentCount: 0,
      headers: null,

      userProfileId,
      folderId,
    };
  }
}
