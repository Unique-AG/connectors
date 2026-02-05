import { createHash } from 'node:crypto';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Client } from '@microsoft/microsoft-graph-client';
import { and, eq, isNull, or } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import type { TypeID } from 'typeid-js';
import type { EmailSyncConfigNamespaced } from '~/config';
import {
  DRIZZLE,
  type DrizzleDatabase,
  type EmailSyncConfig,
  emailSyncConfigs,
  emailSyncMessages,
  userProfiles,
} from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UniqueService } from '~/unique/unique.service';

interface GraphMessage {
  id: string;
  internetMessageId?: string;
  subject?: string;
  from?: {
    emailAddress?: {
      address?: string;
      name?: string;
    };
  };
  toRecipients?: Array<{
    emailAddress?: {
      address?: string;
      name?: string;
    };
  }>;
  receivedDateTime?: string;
  sentDateTime?: string;
  hasAttachments?: boolean;
  '@odata.removed'?: { reason: string };
}

interface DeltaResponse {
  value: GraphMessage[];
  '@odata.nextLink'?: string;
  '@odata.deltaLink'?: string;
}

interface MailFolder {
  id: string;
  displayName: string;
}

interface MailFolderDeltaResponse {
  value: MailFolder[];
  '@odata.nextLink'?: string;
  '@odata.deltaLink'?: string;
}

export interface StartSyncResult {
  status: 'created' | 'already_active' | 'resumed';
  config: EmailSyncConfig;
}

export interface SyncStatusResult {
  status: 'active' | 'paused' | 'stopped' | 'not_found';
  config?: EmailSyncConfig;
  messageCount?: number;
  lastSyncAt?: Date | null;
  lastError?: string | null;
}

export interface StopSyncResult {
  status: 'stopped' | 'not_found';
}

@Injectable()
export class EmailSyncService {
  private readonly logger = new Logger(EmailSyncService.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly uniqueService: UniqueService,
    private readonly config: ConfigService<EmailSyncConfigNamespaced, true>,
    private readonly trace: TraceService,
  ) {}

  @Span()
  public async startSync(
    userProfileId: TypeID<'user_profile'>,
    syncFromDate: Date,
  ): Promise<StartSyncResult> {
    const span = this.trace.getSpan();
    const userProfileIdStr = userProfileId.toString();
    span?.setAttribute('user_profile_id', userProfileIdStr);

    this.logger.log({ userProfileId: userProfileIdStr }, 'Starting email sync for user');

    const existingConfig = await this.db.query.emailSyncConfigs.findFirst({
      where: eq(emailSyncConfigs.userProfileId, userProfileIdStr),
    });

    if (existingConfig) {
      if (existingConfig.status === 'active') {
        this.logger.debug({ configId: existingConfig.id }, 'Email sync already active');
        return { status: 'already_active', config: existingConfig };
      }

      const updatedConfigs = await this.db
        .update(emailSyncConfigs)
        .set({ status: 'active', lastError: null })
        .where(eq(emailSyncConfigs.id, existingConfig.id))
        .returning();

      const updated = updatedConfigs[0];
      if (!updated) {
        throw new Error('Failed to update email sync config');
      }

      this.logger.log({ configId: existingConfig.id }, 'Resumed existing email sync');
      return { status: 'resumed', config: updated };
    }

    const newConfigs = await this.db
      .insert(emailSyncConfigs)
      .values({
        userProfileId: userProfileIdStr,
        status: 'active',
        syncFromDate,
      })
      .returning();

    const newConfig = newConfigs[0];
    if (!newConfig) {
      throw new Error('Failed to create email sync config');
    }

    this.logger.log({ configId: newConfig.id }, 'Created new email sync configuration');
    return { status: 'created', config: newConfig };
  }

  @Span()
  public async getSyncStatus(userProfileId: TypeID<'user_profile'>): Promise<SyncStatusResult> {
    const span = this.trace.getSpan();
    const userProfileIdStr = userProfileId.toString();
    span?.setAttribute('user_profile_id', userProfileIdStr);

    const config = await this.db.query.emailSyncConfigs.findFirst({
      where: eq(emailSyncConfigs.userProfileId, userProfileIdStr),
    });

    if (!config) {
      return { status: 'not_found' };
    }

    const messageCount = await this.db.$count(
      emailSyncMessages,
      eq(emailSyncMessages.emailSyncConfigId, config.id),
    );

    return {
      status: config.status,
      config,
      messageCount,
      lastSyncAt: config.lastSyncAt,
      lastError: config.lastError,
    };
  }

  @Span()
  public async stopSync(userProfileId: TypeID<'user_profile'>): Promise<StopSyncResult> {
    const span = this.trace.getSpan();
    const userProfileIdStr = userProfileId.toString();
    span?.setAttribute('user_profile_id', userProfileIdStr);

    const config = await this.db.query.emailSyncConfigs.findFirst({
      where: eq(emailSyncConfigs.userProfileId, userProfileIdStr),
    });

    if (!config) {
      return { status: 'not_found' };
    }

    await this.db
      .update(emailSyncConfigs)
      .set({ status: 'stopped' })
      .where(eq(emailSyncConfigs.id, config.id));

    this.logger.log({ configId: config.id }, 'Stopped email sync');
    return { status: 'stopped' };
  }

  @Span()
  public async processDeltaSync(config: EmailSyncConfig): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('config_id', config.id);
    span?.setAttribute('user_profile_id', config.userProfileId);

    this.logger.log({ configId: config.id }, 'Starting delta sync for email configuration');

    try {
      const client = this.graphClientFactory.createClientForUser(config.userProfileId);

      const userProfile = await this.db.query.userProfiles.findFirst({
        where: eq(userProfiles.id, config.userProfileId),
      });

      if (!userProfile) {
        throw new Error(`User profile ${config.userProfileId} not found`);
      }

      const folders = await this.fetchAllMailFolders(client);
      this.logger.debug({ folderCount: folders.length }, 'Fetched mail folders');

      for (const folder of folders) {
        await this.processFolderDelta(client, config, folder, userProfile.email ?? '');
      }

      await this.db
        .update(emailSyncConfigs)
        .set({ lastSyncAt: new Date(), lastError: null })
        .where(eq(emailSyncConfigs.id, config.id));

      this.logger.log({ configId: config.id }, 'Completed delta sync successfully');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      this.logger.error({ configId: config.id, error: errorMessage }, 'Delta sync failed');

      await this.db
        .update(emailSyncConfigs)
        .set({ lastError: errorMessage })
        .where(eq(emailSyncConfigs.id, config.id));

      throw error;
    }
  }

  private async fetchAllMailFolders(client: Client): Promise<MailFolder[]> {
    const folders: MailFolder[] = [];
    let nextLink: string | undefined;

    const response = (await client.api('/me/mailFolders').get()) as MailFolderDeltaResponse;

    folders.push(...response.value);
    nextLink = response['@odata.nextLink'];

    while (nextLink) {
      const pageResponse = (await client.api(nextLink).get()) as MailFolderDeltaResponse;
      folders.push(...pageResponse.value);
      nextLink = pageResponse['@odata.nextLink'];
    }

    return folders;
  }

  private async processFolderDelta(
    client: Client,
    config: EmailSyncConfig,
    folder: MailFolder,
    ownerEmail: string,
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.addEvent('processing_folder', { folderId: folder.id, folderName: folder.displayName });

    this.logger.debug({ folderId: folder.id, folderName: folder.displayName }, 'Processing folder');

    let deltaUrl = config.deltaToken
      ? undefined
      : `/me/mailFolders/${folder.id}/messages/delta`;
    let nextLink = config.nextLink;

    const batchSize = this.config.get('emailSync.batchSize', { infer: true });
    let processedCount = 0;

    while (deltaUrl || nextLink) {
      const url = nextLink ?? deltaUrl;
      if (!url) break;

      const response = (await client
        .api(url)
        .header('Prefer', 'IdType="ImmutableId"')
        .top(batchSize)
        .get()) as DeltaResponse;

      for (const message of response.value) {
        if (message['@odata.removed']) {
          continue;
        }

        const receivedAt = message.receivedDateTime
          ? new Date(message.receivedDateTime)
          : undefined;

        if (receivedAt && receivedAt < config.syncFromDate) {
          continue;
        }

        const exists = await this.messageExists(config.id, message);
        if (exists) {
          continue;
        }

        await this.ingestMessage(client, config, message, ownerEmail);
        processedCount++;
      }

      await this.db
        .update(emailSyncConfigs)
        .set({ nextLink: response['@odata.nextLink'] ?? null })
        .where(eq(emailSyncConfigs.id, config.id));

      nextLink = response['@odata.nextLink'];
      deltaUrl = undefined;

      if (response['@odata.deltaLink']) {
        await this.db
          .update(emailSyncConfigs)
          .set({
            deltaToken: response['@odata.deltaLink'],
            nextLink: null,
          })
          .where(eq(emailSyncConfigs.id, config.id));
        break;
      }
    }

    this.logger.debug(
      { folderId: folder.id, processedCount },
      'Finished processing folder',
    );
  }

  private async messageExists(
    configId: string,
    message: GraphMessage,
  ): Promise<boolean> {
    const conditions = [];

    if (message.internetMessageId) {
      conditions.push(eq(emailSyncMessages.internetMessageId, message.internetMessageId));
    }

    if (message.id) {
      conditions.push(eq(emailSyncMessages.immutableId, message.id));
    }

    if (conditions.length === 0) {
      return false;
    }

    const existing = await this.db.query.emailSyncMessages.findFirst({
      where: and(
        eq(emailSyncMessages.emailSyncConfigId, configId),
        or(...conditions),
      ),
    });

    return !!existing;
  }

  private async ingestMessage(
    client: Client,
    config: EmailSyncConfig,
    message: GraphMessage,
    ownerEmail: string,
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.addEvent('ingesting_message', { messageId: message.id });

    this.logger.debug({ messageId: message.id }, 'Ingesting email message');

    const emlResponse = await client
      .api(`/me/messages/${message.id}/$value`)
      .responseType('arraybuffer' as never)
      .get();

    const emlBuffer = emlResponse as ArrayBuffer;
    const emlContent = new Uint8Array(emlBuffer);
    const contentHash = this.computeHash(emlContent);

    const hashExists = await this.db.query.emailSyncMessages.findFirst({
      where: and(
        eq(emailSyncMessages.emailSyncConfigId, config.id),
        eq(emailSyncMessages.contentHash, contentHash),
      ),
    });

    if (hashExists) {
      this.logger.debug({ messageId: message.id }, 'Message already exists by content hash');
      return;
    }

    const recipients = message.toRecipients?.map(
      (r) => r.emailAddress?.address ?? '',
    ).filter(Boolean) ?? [];

    const senderEmail = message.from?.emailAddress?.address ?? '';
    const subject = message.subject ?? 'No Subject';

    const uniqueContentId = await this.uniqueService.ingestEmail(
      {
        subject,
        senderEmail,
        senderName: message.from?.emailAddress?.name ?? '',
        recipients,
        receivedAt: message.receivedDateTime ? new Date(message.receivedDateTime) : new Date(),
        sentAt: message.sentDateTime ? new Date(message.sentDateTime) : undefined,
        ownerEmail,
      },
      {
        id: message.id,
        content: emlContent,
        byteSize: emlContent.length,
      },
    );

    await this.db.insert(emailSyncMessages).values({
      emailSyncConfigId: config.id,
      internetMessageId: message.internetMessageId ?? null,
      immutableId: message.id,
      contentHash,
      subject,
      senderEmail,
      senderName: message.from?.emailAddress?.name ?? null,
      recipients,
      receivedAt: message.receivedDateTime ? new Date(message.receivedDateTime) : null,
      sentAt: message.sentDateTime ? new Date(message.sentDateTime) : null,
      byteSize: emlContent.length,
      hasAttachments: message.hasAttachments ?? false,
      uniqueContentId,
      ingestedAt: new Date(),
    });

    this.logger.log({ messageId: message.id, uniqueContentId }, 'Email message ingested');
  }

  private computeHash(content: Uint8Array): string {
    return createHash('sha256').update(content).digest('hex');
  }

  @Span()
  public async getActiveConfigs(): Promise<EmailSyncConfig[]> {
    return this.db.query.emailSyncConfigs.findMany({
      where: eq(emailSyncConfigs.status, 'active'),
    });
  }

  @Span()
  public async retryFailedMessages(config: EmailSyncConfig): Promise<number> {
    const failedMessages = await this.db.query.emailSyncMessages.findMany({
      where: and(
        eq(emailSyncMessages.emailSyncConfigId, config.id),
        isNull(emailSyncMessages.ingestedAt),
      ),
    });

    return failedMessages.length;
  }
}
