import {
  Client,
  PageCollection,
  PageIterator,
  PageIteratorCallback,
} from '@microsoft/microsoft-graph-client';
import { MailFolder } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { and, eq, inArray, sql } from 'drizzle-orm';
import { serializeError } from 'serialize-error-cjs';
import { TypeID } from 'typeid-js';
import { BatchProcessor } from '../batch/batch-processor.decorator';
import { DRIZZLE, DrizzleDatabase } from '../drizzle';
import {
  FolderUpdateZod,
  folders as foldersTable,
  folderUpdateSchemaCamelized,
  userProfiles,
} from '../drizzle/schema';
import { EmailSyncService } from '../email/email-sync.service';
import { GraphClientFactory } from '../msgraph/graph-client.factory';
import { SubscriptionEvent } from '../msgraph/subscription.events';
import { SubscriptionService } from '../msgraph/subscription.service';
import { normalizeError } from '../utils/normalize-error';
import { FolderEvents, FolderSyncEvent } from './folder.events';

const FOLDER_SELECT_FIELDS =
  'id,displayName,parentFolderId,childFolderCount,unreadItemCount,totalItemCount';
type FolderWithName = MailFolder & { name: string };

@Injectable()
export class FolderService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly subscriptionService: SubscriptionService,
    private readonly emailSyncService: EmailSyncService,
  ) {}

  @BatchProcessor({ table: 'folders', operation: 'PUT' })
  public async onPut(
    userProfileId: TypeID<'user_profile'>,
    id: string,
    data?: Record<string, unknown>,
  ): Promise<void> {
    this.logger.warn({
      msg: 'This should never be called by the frontend, as the folders are created by the backend.',
      userProfileId,
      operationId: id,
      data,
    });
  }

  @BatchProcessor({ table: 'folders', operation: 'PATCH', schema: folderUpdateSchemaCamelized })
  public async onPatch(
    userProfileId: TypeID<'user_profile'>,
    id: string,
    data?: FolderUpdateZod,
  ): Promise<void> {
    this.logger.debug({
      msg: 'Patching folder',
      userProfileId: userProfileId.toString(),
      operationId: id,
      data,
    });

    if (!data) return;
    await this.db
      .update(foldersTable)
      .set(data)
      .where(
        and(eq(foldersTable.userProfileId, userProfileId.toString()), eq(foldersTable.id, id)),
      );

    const folder = await this.db.query.folders.findFirst({
      where: and(eq(foldersTable.userProfileId, userProfileId.toString()), eq(foldersTable.id, id)),
      with: {
        subscription: true,
      },
    });
    if (!folder) throw new Error('Folder not found');

    const syncEnabled = data.activatedAt && !data.deactivatedAt;
    if (syncEnabled) {
      this.logger.debug({
        msg: 'Sync activated for folder',
        userProfileId: userProfileId.toString(),
        folderId: id,
      });

      // Create subscription for folder changes
      await this.subscriptionService.createSubscription(userProfileId, 'folder', folder);

      // Trigger initial email sync
      this.logger.log({
        msg: 'Starting initial email sync for folder',
        userProfileId: userProfileId.toString(),
        folderId: id,
        folderName: folder.name,
      });

      try {
        await this.emailSyncService.syncFolderEmails(userProfileId, id);
      } catch (error) {
        this.logger.error({
          msg: 'Failed to perform initial email sync',
          folderId: id,
          error: serializeError(normalizeError(error)),
        });
        // Don't throw here - we still want the folder to be marked as active
        // The sync can be retried later
      }
    }

    const syncDisabled = data.deactivatedAt;
    if (syncDisabled) {
      this.logger.debug({
        msg: 'Sync deactivated for folder',
        userProfileId: userProfileId.toString(),
        folderId: id,
      });
      if (folder.subscription)
        await this.subscriptionService.deleteSubscription(
          TypeID.fromString(folder.subscription.id, 'subscription'),
        );
    }
  }

  @BatchProcessor({ table: 'folders', operation: 'DELETE' })
  public async onDelete(
    userProfileId: TypeID<'user_profile'>,
    id: string,
    data?: Record<string, unknown>,
  ): Promise<void> {
    this.logger.warn({
      msg: 'This should never be called by the frontend, as the folders are managed in the backend.',
      userProfileId,
      operationId: id,
      data,
    });
  }

  @OnEvent(FolderEvents.FolderSync)
  public async syncFolders(event: FolderSyncEvent) {
    const { userProfileId } = event;
    const graphClient = this.graphClientFactory.createClientForUser(userProfileId);
    try {
      const folders: FolderWithName[] = [];
      const response: PageCollection = await graphClient
        .api('/me/mailFolders')
        .select(FOLDER_SELECT_FIELDS)
        .top(200)
        .get();

      const callback: PageIteratorCallback = (data: MailFolder) => {
        folders.push({ ...data, name: data.displayName ?? '<unnamed>' });
        return true;
      };

      const pageIterator = new PageIterator(graphClient, response, callback);
      await pageIterator.iterate();

      const topLevelFoldersSnapshot = [...folders];
      for (const folder of topLevelFoldersSnapshot) {
        if (!folder.id) continue;
        if (folder.childFolderCount && folder.childFolderCount > 0) {
          const descendants = await this.getChildFolders(graphClient, folder.id, folder.name);
          folders.push(...descendants);
        }
      }

      this.logger.log({
        msg: 'Synced folders for user',
        userProfileId,
        folderCount: folders.length,
      });

      await this.saveFolders(userProfileId, folders);
    } catch (error) {
      this.logger.error({
        msg: 'Failed to sync folders',
        error: serializeError(normalizeError(error)),
      });
      throw error;
    }
  }

  private async getChildFolders(
    graphClient: Client,
    folderId: string,
    parentName: string,
  ): Promise<FolderWithName[]> {
    const children: FolderWithName[] = [];
    const response = await graphClient
      .api(`/me/mailFolders/${folderId}/childFolders`)
      .select(FOLDER_SELECT_FIELDS)
      .top(200)
      .get();

    const callback: PageIteratorCallback = (data: MailFolder) => {
      const childName = `${parentName} / ${data.displayName ?? '<unnamed>'}`;
      children.push({ ...data, name: childName });
      return true;
    };

    const pageIterator = new PageIterator(graphClient, response, callback);
    await pageIterator.iterate();

    const directChildrenSnapshot = [...children];
    for (const child of directChildrenSnapshot) {
      if (!child.id) continue;
      if (child.childFolderCount && child.childFolderCount > 0) {
        const descendants = await this.getChildFolders(graphClient, child.id, child.name);
        children.push(...descendants);
      }
    }

    return children;
  }

  private async saveFolders(userProfileId: TypeID<'user_profile'>, folders: FolderWithName[]) {
    const existingFolders = await this.db.query.folders.findMany({
      columns: {
        folderId: true,
      },
    });
    const foldersToDelete = existingFolders.filter(
      (f) => !folders.some((folder) => folder.id === f.folderId),
    );

    await this.db
      .insert(foldersTable)
      .values(
        folders
          .filter((folder) => folder.id)
          .map((folder) => ({
            name: folder.name,
            originalName: folder.displayName,
            // biome-ignore lint/style/noNonNullAssertion: map is filtered!
            folderId: folder.id!,
            parentFolderId: folder.parentFolderId,
            childFolderCount: folder.childFolderCount ?? 0,
            userProfileId: userProfileId.toString(),
          })),
      )
      .onConflictDoUpdate({
        target: foldersTable.folderId,
        set: {
          name: sql`excluded.name`,
          originalName: sql`excluded.original_name`,
          parentFolderId: sql`excluded.parent_folder_id`,
          childFolderCount: sql`excluded.child_folder_count`,
        },
      });

    if (foldersToDelete.length > 0) {
      await this.db.delete(foldersTable).where(
        inArray(
          foldersTable.folderId,
          foldersToDelete.map((f) => f.folderId),
        ),
      );
    }

    await this.db
      .update(userProfiles)
      .set({ syncLastSyncedAt: new Date().toISOString() })
      .where(eq(userProfiles.id, userProfileId.toString()));
  }
}
