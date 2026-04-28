import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { count, eq, notInArray } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { chunk } from 'remeda';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessDirectories,
  delegatedAccessPipeline,
  userProfiles,
} from '~/db';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

interface FolderNode {
  id: string;
  childFolderCount: number;
  childFolders?: FolderNode[];
}

@Injectable()
export class VerifyDelegatedAccessCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run(input: { pipelineId: string }): Promise<void> {
    const { pipelineId } = input;

    const [pipeline] = await this.db
      .select({
        delegateUserId: delegatedAccessPipeline.delegateUserId,
        ownerUserId: delegatedAccessPipeline.ownerUserId,
      })
      .from(delegatedAccessPipeline)
      .where(eq(delegatedAccessPipeline.id, pipelineId));

    if (!pipeline) {
      this.logger.warn({ pipelineId, msg: 'Pipeline not found, skipping verification' });
      return;
    }

    const { delegateUserId, ownerUserId } = pipeline;

    const [ownerProfile] = await this.db
      .select({ email: userProfiles.email })
      .from(userProfiles)
      .where(eq(userProfiles.id, ownerUserId));

    const ownerEmail = ownerProfile?.email;
    if (!ownerEmail) {
      this.logger.warn({
        pipelineId,
        ownerUserId,
        msg: 'Owner email not found, skipping verification',
      });
      return;
    }

    const client = this.graphClientFactory.createClientForUser(delegateUserId);

    let hasTransientError = false;
    const folderIds = await this.readAllFolders({ client, ownerEmail });

    const accesibleFolderIds: string[] = [];
    for (const folderIdsChunk of chunk(folderIds, 100)) {
      const foldersWithAccessFetched = await Promise.all(
        folderIdsChunk.map(async (folderId) => {
          try {
            await client
              .api(`/users/${ownerEmail}/mailFolders/${folderId}/messages`)
              .select('id')
              .top(1)
              .get();
            return { canRead: true, folderId };
          } catch (error) {
            if (error instanceof GraphError) {
              if (error.statusCode === 403 || error.statusCode === 404) {
                return { canRead: false, folderId, reason: 'no-access', error };
              }
              if (error.statusCode === 429 || (error.statusCode >= 500 && error.statusCode < 600)) {
                hasTransientError = true;
                return { canRead: false, folderId, reason: 'transient-error', error };
              }
            }
            return { canRead: false, folderId, reason: 'unexpected-error', error };
          }
        }),
      );
      accesibleFolderIds.push(
        ...foldersWithAccessFetched.filter((item) => item.canRead).map((item) => item.folderId),
      );

      if (hasTransientError) {
        break;
      }
    }

    await this.db
      .delete(delegatedAccessDirectories)
      .where(notInArray(delegatedAccessDirectories.directoryId, accesibleFolderIds));

    await this.db
      .insert(delegatedAccessDirectories)
      .values(
        accesibleFolderIds.map((directoryId) => ({
          pipelineId,
          directoryId,
        })),
      )
      .onConflictDoNothing();

    const [result] = await this.db
      .select({ count: count() })
      .from(delegatedAccessDirectories)
      .where(eq(delegatedAccessDirectories.pipelineId, pipelineId));
    const dirCount = result?.count ?? 0;

    if (dirCount === 0 && !hasTransientError) {
      await this.db
        .delete(delegatedAccessPipeline)
        .where(eq(delegatedAccessPipeline.id, pipelineId));
      this.logger.log({ pipelineId, msg: 'No accessible directories, pipeline deleted' });
      return;
    }

    if (!hasTransientError) {
      await this.db
        .update(delegatedAccessPipeline)
        .set({ lastVerifiedAt: new Date() })
        .where(eq(delegatedAccessPipeline.id, pipelineId));
      this.logger.log({ pipelineId, dirCount, msg: 'Pipeline lastVerifiedAt updated' });
    }
  }

  private async readAllFolders({
    client,
    ownerEmail,
  }: {
    client: Client;
    ownerEmail: string;
  }): Promise<string[]> {
    const shouldExpand = (folder: FolderNode) =>
      folder.childFolderCount > 0 &&
      (!folder.childFolders || folder.childFolders.length !== folder.childFolderCount);

    const expandRecursive = async (folder: FolderNode): Promise<void> => {
      if (!shouldExpand(folder)) {
        return;
      }

      const expanded = await client
        .api(`/users/${ownerEmail}/mailFolders/${folder.id}`)
        .top(500)
        .expand('childFolders')
        .get();
      folder.childFolders = expanded?.childFolders ?? [];

      await Promise.all(folder.childFolders?.filter(shouldExpand).map(expandRecursive) ?? []);
    };

    const rootFolders: FolderNode[] = [];
    let response = await client
      .api(`/users/${ownerEmail}/mailFolders`)
      .top(500)
      .expand('childFolders')
      .get();
    rootFolders.push(...(response?.value ?? []));

    while (response?.['@odata.nextLink']) {
      response = await client.api(response['@odata.nextLink']).get();
      rootFolders.push(...(response?.value ?? []));
    }

    await Promise.all(
      rootFolders.flatMap((root) =>
        (root.childFolders ?? []).filter(shouldExpand).map(expandRecursive),
      ),
    );

    const flattenFolders = (items: FolderNode[]): Array<string> =>
      items.flatMap((item) => [item.id, ...flattenFolders(item.childFolders ?? [])]);

    return flattenFolders(rootFolders);
  }
}
