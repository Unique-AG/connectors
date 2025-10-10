import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Client } from '@microsoft/microsoft-graph-client';
import { Message } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2, OnEvent } from '@nestjs/event-emitter';
import { and, eq } from 'drizzle-orm';
import { debounce } from 'lodash';
import { serializeError } from 'serialize-error-cjs';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, Folder, folders as foldersTable } from '../drizzle';
import { GraphClientFactory } from '../msgraph/graph-client.factory';
import { SubscriptionEvent } from '../msgraph/subscription.events';
import { normalizeError } from '../utils/normalize-error';
import {
  EmailDeltaSyncRequestedEvent,
  EmailEvents,
  EmailSyncCompletedEvent,
  EmailSyncFailedEvent,
  EmailSyncStartedEvent,
} from './email.events';

interface DeltaResponse {
  '@odata.context'?: string;
  '@odata.nextLink'?: string;
  '@odata.deltaLink'?: string;
  value: Message[];
}

@Injectable()
export class EmailSyncService {
  private readonly logger = new Logger(EmailSyncService.name);
  private readonly PAGE_SIZE = 100;
  private readonly SYNC_DEBOUNCE_MS = 1000;

  private readonly debouncedSyncs = new Map<string, ReturnType<typeof debounce>>();
  private readonly runningSyncs = new Map<string, Promise<void>>();
  private readonly pendingSyncRequests = new Map<string, boolean>();

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly eventEmitter: EventEmitter2,
    private readonly amqpConnection: AmqpConnection,
  ) {}

  public async syncFolderEmails(
    userProfileId: TypeID<'user_profile'>,
    folderId: string,
  ): Promise<void> {
    const folder = await this.db.query.folders.findFirst({
      where: and(
        eq(foldersTable.id, folderId),
        eq(foldersTable.userProfileId, userProfileId.toString()),
      ),
    });

    if (!folder) throw new Error(`Folder not found: ${folderId}`);

    const graphClient = this.graphClientFactory.createClientForUser(userProfileId);

    try {
      const isInitialSync = !folder.syncToken;

      this.logger.log({
        msg: isInitialSync ? 'Starting initial sync' : 'Starting delta sync',
        folderId,
        folderName: folder.name,
        userProfileId: userProfileId.toString(),
      });

      this.eventEmitter.emit(
        EmailEvents.EmailSyncStarted,
        new EmailSyncStartedEvent(userProfileId, folderId, folder.name, isInitialSync),
      );

      const deltaToken = await this.performDeltaSync(
        graphClient,
        folder,
        userProfileId,
        isInitialSync,
      );

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
      });

      this.eventEmitter.emit(
        EmailEvents.EmailSyncFailed,
        new EmailSyncFailedEvent(userProfileId, folderId, folder.name, normalizeError(error)),
      );

      throw error;
    }
  }

  @OnEvent(EmailEvents.EmailDeltaSyncRequested)
  public async onDeltaSyncRequested(event: EmailDeltaSyncRequestedEvent) {
    try {
      await this.syncFolderEmails(event.userProfileId, event.folderId);
    } catch (error) {
      this.logger.error({
        msg: 'Failed to perform delta sync',
        folderId: event.folderId,
        error: serializeError(normalizeError(error)),
      });
    }
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
    isInitialSync: boolean,
  ): Promise<string> {
    let url: string;

    url = folder.syncToken
      ? folder.syncToken
      : `/me/mailFolders/${folder.folderId}/messages/delta?$top=${this.PAGE_SIZE}`;

    let deltaLink: string | undefined;
    // let allEmails: Message[] = [];
    // let deletedIds: string[] = [];
    let hasMorePages = true;
    let totalEmailsProcessed = 0;
    // let totalEmailsDeleted = 0;

    while (hasMorePages) {
      const response: DeltaResponse = await graphClient.api(url).get();

      // // Process messages
      // const emailsInPage = response.value.filter(
      //   (item) => !(item as unknown as DeletedItem)['@removed'],
      // );

      // // Process deleted items
      // const deletedInPage = response.value
      //   .filter((item) => (item as unknown as DeletedItem)['@removed'])
      //   // biome-ignore lint/style/noNonNullAssertion: Microsoft Graph API returns deleted items with an id
      //   .map((item) => item.id!);

      // allEmails = allEmails.concat(emailsInPage);
      // deletedIds = deletedIds.concat(deletedInPage);
      for (const message of response.value) {
        this.amqpConnection.publish('email.pipeline', 'email.ingest', {
          message,
          userProfileId: userProfileId.toString(),
          folderId: folder.id,
        });
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

    // Process emails in batches to avoid memory issues
    // const BATCH_SIZE = 100;
    // for (let i = 0; i < allEmails.length; i += BATCH_SIZE) {
    //   const batch = allEmails.slice(i, i + BATCH_SIZE);
    //   await this.emailService.upsertEmails(userProfileId, folder.id, batch);
    // }
    // totalEmailsProcessed = allEmails.length;

    // if (deletedIds.length > 0) {
    //   await this.emailService.deleteEmails(userProfileId, deletedIds);
    //   totalEmailsDeleted = deletedIds.length;
    // }

    this.logger.log({
      msg: 'Delta sync completed',
      folderId: folder.id,
      folderName: folder.name,
      emailsUpserted: totalEmailsProcessed,
      // emailsDeleted: totalEmailsDeleted,
      isInitialSync,
    });

    this.eventEmitter.emit(
      EmailEvents.EmailSyncCompleted,
      new EmailSyncCompletedEvent(
        userProfileId,
        folder.id,
        folder.name,
        totalEmailsProcessed,
        // totalEmailsDeleted,
        deltaLink || '',
      ),
    );

    if (!deltaLink) throw new Error('No delta link returned from Microsoft Graph');

    return deltaLink;
  }
}
