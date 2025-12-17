import { Client } from '@microsoft/microsoft-graph-client';
import { Message } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { and, eq } from 'drizzle-orm';
import { debounce } from 'lodash';
import { serializeError } from 'serialize-error-cjs';
import { TypeID } from 'typeid-js';
import {
  DRIZZLE,
  DrizzleDatabase,
  emails as emailsTable,
  Folder,
  folders as foldersTable,
} from '../../drizzle';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import { normalizeError } from '../../utils/normalize-error';
import { SubscriptionEvent } from '../subscription/subscription.events';
import { AmqpOrchestratorService } from './amqp-orchestrator.service';
import {
  EmailDeltaSyncRequestedEvent,
  EmailEvents,
  EmailFullSyncRequestedEvent,
} from './email.events';

interface DeltaResponse {
  '@odata.context'?: string;
  '@odata.nextLink'?: string;
  '@odata.deltaLink'?: string;
  value: Message[];
}

export interface DeletedItem {
  id: string;
  '@removed'?: {
    reason: string;
  };
}

@Injectable()
export class EmailSyncService {
  private readonly logger = new Logger(EmailSyncService.name);
  private readonly PAGE_SIZE = 100;
  private readonly SYNC_DEBOUNCE_MS = 1000;
  private readonly SELECT_FIELDS = [
    'id',
    'conversationId',
    'internetMessageId',
    'webLink',
    'changeKey',
    'from',
    'sender',
    'replyTo',
    'toRecipients',
    'ccRecipients',
    'bccRecipients',
    'sentDateTime',
    'receivedDateTime',
    'subject',
    'bodyPreview',
    'body',
    'uniqueBody',
    'importance',
    'isRead',
    'isDraft',
    'hasAttachments',
    'internetMessageHeaders',
  ];

  private readonly debouncedSyncs = new Map<string, ReturnType<typeof debounce>>();
  private readonly runningSyncs = new Map<string, Promise<void>>();
  private readonly pendingSyncRequests = new Map<string, boolean>();

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly amqpOrchestrator: AmqpOrchestratorService,
  ) {}

  @OnEvent(EmailEvents.EmailFullSyncRequested)
  public async onFullSyncRequested(event: EmailFullSyncRequestedEvent) {
    await this.syncFolderEmails(event.userProfileId, event.folderId, true);
  }

  @OnEvent(EmailEvents.EmailDeltaSyncRequested)
  public async onDeltaSyncRequested(event: EmailDeltaSyncRequestedEvent) {
    await this.syncFolderEmails(event.userProfileId, event.folderId);
  }

  /**
   * Subscription events for folders notify us of new, updated or deleted emails.
   * !These events don't mean that folders are created or updated, only the emails inside them.
   */
  @OnEvent('subscription.notification.for.folder.created')
  @OnEvent('subscription.notification.for.folder.updated')
  @OnEvent('subscription.notification.for.folder.deleted')
  public async onFolderChange(event: SubscriptionEvent) {
    this.logger.debug({
      msg: 'New, updated or deleted email event received. Scheduling debounced sync.',
      event,
    });

    const folderId = event.subscriptionForId;

    let debouncedSync = this.debouncedSyncs.get(folderId);
    if (!debouncedSync) {
      debouncedSync = debounce(() => this.executeFolderSync(folderId), this.SYNC_DEBOUNCE_MS, {
        leading: false,
        trailing: true,
      });
      this.debouncedSyncs.set(folderId, debouncedSync);
    }

    debouncedSync();
  }

  /**
   * Executes a full or partial sync for a folder without checking any pre-conditions
   * like if there is already a sync in progress or if the folder is activated for sync or not.
   */
  private async syncFolderEmails(
    userProfileId: TypeID<'user_profile'>,
    folderId: string,
    forceInitialSync: boolean = false,
  ): Promise<void> {
    const folder = await this.db.query.folders.findFirst({
      where: and(
        eq(foldersTable.id, folderId),
        eq(foldersTable.userProfileId, userProfileId.toString()),
      ),
    });

    if (!folder) throw new Error(`Folder not found: ${folderId}`);

    if (forceInitialSync) folder.syncToken = null;

    const graphClient = this.graphClientFactory.createClientForUser(userProfileId);

    try {
      const isInitialSync = !folder.syncToken;

      this.logger.log({
        msg: isInitialSync ? 'Starting initial sync' : 'Starting delta sync',
        folderId,
        folderName: folder.name,
        userProfileId: userProfileId.toString(),
      });

      const deltaToken = await this.performDeltaSync(graphClient, folder, userProfileId);

      await this.db
        .update(foldersTable)
        .set({
          syncToken: deltaToken,
          lastSyncedAt: new Date().toISOString(),
        })
        .where(eq(foldersTable.id, folderId));

      this.logger.log({
        msg: 'Email sync completed',
        folderId,
        folderName: folder.name,
        userProfileId: userProfileId.toString(),
      });
    } catch (error) {
      this.logger.error({
        msg: 'Failed to sync emails',
        folderId,
        folderName: folder.name,
        error: serializeError(normalizeError(error)),
        forcedInitialSync: forceInitialSync,
      });

      // We do not re-throw here, as all logging was done.
    }
  }

  /**
   * Executes a full or partial sync AND validates all pre-conditions (sync in progress, folder activated, etc.)
   * Use this method for events from subscriptions, so we can be sure that the sync is valid and still running.
   */
  private async executeFolderSync(folderId: string): Promise<void> {
    const runningSync = this.runningSyncs.get(folderId);
    if (runningSync) {
      this.logger.debug({
        msg: 'Sync already running for folder, marking as pending',
        folderId,
      });
      this.pendingSyncRequests.set(folderId, true);
      return;
    }

    this.pendingSyncRequests.delete(folderId);

    const folder = await this.db.query.folders.findFirst({
      where: eq(foldersTable.id, folderId),
      with: {
        userProfile: true,
      },
    });

    if (!folder) {
      this.logger.warn({
        msg: 'Folder not found for subscription event',
        folderId,
      });
      return;
    }

    if (!folder.activatedAt || folder.deactivatedAt) {
      this.logger.debug({
        msg: 'Folder sync not active, skipping',
        folderId: folder.id,
      });
      return;
    }

    const syncPromise = this.syncFolderEmails(
      TypeID.fromString(folder.userProfileId, 'user_profile'),
      folder.id,
    )
      .catch((error) => {
        this.logger.error({
          msg: 'Failed to sync emails on folder change',
          folderId: folder.id,
          error: serializeError(normalizeError(error)),
        });
      })
      .finally(async () => {
        this.runningSyncs.delete(folderId);

        if (this.pendingSyncRequests.has(folderId)) {
          this.logger.debug({
            msg: 'Pending sync request detected, triggering new sync',
            folderId,
          });
          await this.executeFolderSync(folderId);
        }
      });

    this.runningSyncs.set(folderId, syncPromise);
    await syncPromise;
  }

  private async performDeltaSync(
    graphClient: Client,
    folder: Folder,
    userProfileId: TypeID<'user_profile'>,
  ): Promise<string> {
    let url: string;

    url = folder.syncToken
      ? folder.syncToken
      : `/me/mailFolders/${folder.folderId}/messages/delta?$top=${this.PAGE_SIZE}&$select=${this.SELECT_FIELDS.join(',')}&$expand=attachments`;

    const isInitialSync = !folder.syncToken;
    let deltaLink: string | undefined;
    let hasMorePages = true;
    let totalEmailsProcessed = 0;

    while (hasMorePages) {
      const response: DeltaResponse = await graphClient.api(url).get();

      for (const message of response.value) {
        let emailId: TypeID<'email'> | undefined;
        const isDeleted = (message as unknown as DeletedItem)['@removed'] !== undefined;

        if (isDeleted) {
          const savedEmail = await this.db.query.emails.findFirst({
            where: and(
              // biome-ignore lint/style/noNonNullAssertion: All messages always have an id. The MS type is faulty.
              eq(emailsTable.messageId, message.id!),
              eq(emailsTable.userProfileId, userProfileId.toString()),
              eq(emailsTable.folderId, folder.id),
            ),
          });
          if (!savedEmail) throw new Error('Email not found');
          emailId = TypeID.fromString(savedEmail.id, 'email');
        } else {
          // Ensure the message is present in the database for reference
          const [savedEmail] = await this.db
            .insert(emailsTable)
            .values({
              // biome-ignore lint/style/noNonNullAssertion: All messages always have an id. The MS type is faulty.
              messageId: message.id!,
              userProfileId: userProfileId.toString(),
              folderId: folder.id,
              version: message.changeKey,
            })
            .onConflictDoUpdate({
              target: emailsTable.messageId,
              set: {
                version: message.changeKey,
              },
            })
            .returning();
          if (!savedEmail) throw new Error('Failed to save email');
          emailId = TypeID.fromString(savedEmail.id, 'email');
        }

        await this.amqpOrchestrator.startPipeline(
          userProfileId.toString(),
          folder.id,
          emailId.toString(),
          message,
        );

        totalEmailsProcessed++;
      }

      // Check for next page or delta link
      if (response['@odata.nextLink']) {
        url = response['@odata.nextLink'];
      } else if (response['@odata.deltaLink']) {
        deltaLink = response['@odata.deltaLink'];
        hasMorePages = false;
      } else {
        hasMorePages = false;
      }

      // Log progress for initial sync
      if (isInitialSync && totalEmailsProcessed > 0 && totalEmailsProcessed % 500 === 0) {
        this.logger.debug({
          msg: 'Initial sync progress',
          emailsProcessed: totalEmailsProcessed,
          folderId: folder.id,
        });
      }
    }

    this.logger.log({
      msg: 'Delta sync completed',
      folderId: folder.id,
      folderName: folder.name,
      emailsUpserted: totalEmailsProcessed,
      isInitialSync,
    });

    if (!deltaLink) throw new Error('No delta link returned from Microsoft Graph');

    return deltaLink;
  }
}
