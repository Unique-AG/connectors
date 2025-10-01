import {
  Client,
  PageCollection,
  PageIterator,
  PageIteratorCallback,
} from '@microsoft/microsoft-graph-client';
import { MailFolder } from '@microsoft/microsoft-graph-types';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { serializeError } from 'serialize-error-cjs';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, folderArraySchema, folders } from '../../drizzle';
import { folders as foldersTable, userProfiles } from '../../drizzle/schema';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import { normalizeError } from '../../utils/normalize-error';

const FOLDER_SELECT_FIELDS =
  'id,displayName,parentFolderId,childFolderCount,unreadItemCount,totalItemCount';
type FolderWithName = MailFolder & { name: string };

@Injectable()
export class FoldersService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
  ) {}

  public async getFolders(userProfileId: TypeID<'user_profile'>) {
    const result = await this.db.query.folders.findMany({
      where: and(eq(folders.userProfileId, userProfileId.toString())),
    });
    return folderArraySchema.parse(result);
  }

  public async activateSync(userProfileId: TypeID<'user_profile'>, folderId: string) {
    await this.db
      .update(folders)
      .set({ activatedAt: new Date() })
      .where(and(eq(folders.userProfileId, userProfileId.toString()), eq(folders.id, folderId)));
  }

  public async deactivateSync(userProfileId: TypeID<'user_profile'>, folderId: string) {
    await this.db
      .update(folders)
      .set({ deactivatedAt: new Date() })
      .where(and(eq(folders.userProfileId, userProfileId.toString()), eq(folders.id, folderId)));
  }

  public async syncFolders(userProfileId: TypeID<'user_profile'>) {
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
    await this.db.insert(foldersTable).values(
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
    );
    await this.db
      .update(userProfiles)
      .set({ syncLastSyncedAt: new Date() })
      .where(eq(userProfiles.id, userProfileId.toString()));
  }
}
