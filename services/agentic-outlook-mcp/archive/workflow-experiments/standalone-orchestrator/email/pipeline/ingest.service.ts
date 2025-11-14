import { AmqpConnection, RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Message } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from '@opentelemetry/api';
import { ConsumeMessage } from 'amqplib';
import { snakeCase } from 'lodash';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, EmailInput } from '../../../drizzle';
import { addSpanEvent } from '../../../utils/add-span-event';
import { EmailService } from '../email.service';
import { DeletedItem } from '../email-sync.service';
import { OrchestratorEventType } from '../orchestrator.messages';
import { RetryService } from '../retry.service';
import { TracePropagationService } from '../trace-propagation.service';
import { PipelineStageBase, PipelineStageConfig } from './pipeline-stage.base';

interface IngestMessage {
  message: Message;
  userProfileId: string;
  folderId: string;
  emailId: string;
}

@Injectable()
export class IngestService extends PipelineStageBase<IngestMessage> {
  protected readonly logger = new Logger(this.constructor.name);
  protected readonly config: PipelineStageConfig = {
    spanName: 'email.pipeline.ingest',
    retryRoutingKey: 'email.ingest.retry',
    successEvent: OrchestratorEventType.IngestCompleted,
    failureEvent: OrchestratorEventType.IngestFailed,
  };
  private readonly foldersMap = new Map<string, string>();

  public constructor(
    amqpConnection: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly emailService: EmailService,
    retryService: RetryService,
    tracePropagation: TracePropagationService,
  ) {
    super(amqpConnection, retryService, tracePropagation);
  }

  @RabbitSubscribe({
    exchange: 'email.pipeline',
    routingKey: 'email.ingest',
    queue: 'q.email.ingest',
  })
  public async ingest(ingestMessage: IngestMessage, amqpMessage: ConsumeMessage) {
    return this.executeStage(
      ingestMessage,
      amqpMessage,
      {
        'email.id': ingestMessage.emailId,
        'user.id': ingestMessage.userProfileId,
        'folder.id': ingestMessage.folderId,
        'pipeline.step': 'ingest',
      },
    );
  }

  protected getMessageIdentifiers(message: IngestMessage) {
    return {
      userProfileId: message.userProfileId,
      emailId: message.emailId,
      folderId: message.folderId,
      // biome-ignore lint/style/noNonNullAssertion: All messages always have an id. The MS type is faulty.
      messageId: message.message.id!,
    };
  }

  protected buildSuccessPayload(message: IngestMessage, additionalData?: unknown) {
    const data = additionalData as { savedId?: string } | undefined;
    return {
      userProfileId: message.userProfileId,
      folderId: message.folderId,
      emailId: data?.savedId || message.emailId,
    };
  }

  protected buildFailurePayload(message: IngestMessage, _error: string) {
    return {
      userProfileId: message.userProfileId,
      emailId: message.emailId,
      folderId: message.folderId,
      // biome-ignore lint/style/noNonNullAssertion: All messages always have an id. The MS type is faulty.
      messageId: message.message.id!,
    };
  }

  protected async processMessage(
    message: IngestMessage,
    _amqpMessage: ConsumeMessage,
    span: Span,
  ): Promise<{ savedId: string } | undefined> {
    const { message: graphMessage, userProfileId, folderId } = message;
    // biome-ignore lint/style/noNonNullAssertion: All messages always have an id. The MS type is faulty.
    const messageId = graphMessage.id!;
    
    // This can cause data inconsistency if a folder is changed while ingesting.
    await this.ensureFoldersMap();

    const isDeleted = (graphMessage as unknown as DeletedItem)['@removed'] !== undefined;
    if (isDeleted) {
      addSpanEvent(span, 'email.deleted');
      await this.emailService.deleteEmails(TypeID.fromString(userProfileId, 'user_profile'), [
        messageId,
      ]);
      return;
    }

    const mappedEmail = this.mapMessageToEmail({ message: graphMessage, userProfileId, folderId });

    const savedId = await this.emailService.upsertEmail(
      TypeID.fromString(userProfileId, 'user_profile'),
      folderId,
      mappedEmail,
    );

    addSpanEvent(span, 'email.saved', { 'email.id': savedId.toString() });
    
    return { savedId: savedId.toString() };
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

      userProfileId,
      folderId,
    };
  }
}
