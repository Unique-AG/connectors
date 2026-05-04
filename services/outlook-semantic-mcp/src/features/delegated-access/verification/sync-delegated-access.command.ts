import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, count, eq, notInArray } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import pLimit from 'p-limit';
import { chunk } from 'remeda';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessDirectories,
  delegatedAccessPipelines,
  userProfiles,
} from '~/db';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { GenericRateLimitError } from '~/utils/is-rate-limit-error';

interface FolderNode {
  id: string;
  childFolderCount: number;
  childFolders?: FolderNode[];
}

interface FolderWithErrors {
  canRead: boolean;
  folderId: string;
  reason: string;
  error: unknown;
}

@Injectable()
export class SyncDelegatedAccessCommand {
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
        delegateUserId: delegatedAccessPipelines.delegateUserId,
        ownerUserId: delegatedAccessPipelines.ownerUserId,
      })
      .from(delegatedAccessPipelines)
      .where(eq(delegatedAccessPipelines.id, pipelineId));

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

    const folderIds = await this.readAllFolders({ client, ownerEmail });
    let foldersWithErrors: FolderWithErrors[] = [];
    const accessibleFolderIds: string[] = [];
    for (const folderIdsChunk of chunk(folderIds, 100)) {
      const foldersWithAccessFetched = await Promise.all(
        folderIdsChunk.map(
          async (folderId): Promise<{ canRead: true; folderId: string } | FolderWithErrors> => {
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
                if (
                  error.statusCode === 429 ||
                  (error.statusCode >= 500 && error.statusCode < 600)
                ) {
                  return { canRead: false, folderId, reason: 'transient-error', error };
                }
              }
              return { canRead: false, folderId, reason: 'unexpected-error', error };
            }
          },
        ),
      );
      foldersWithErrors = foldersWithAccessFetched.filter(
        (item) => !item.canRead && item.reason !== 'no-access',
      ) as FolderWithErrors[];
      accessibleFolderIds.push(
        ...foldersWithAccessFetched.filter((item) => item.canRead).map((item) => item.folderId),
      );

      if (foldersWithErrors.length > 0) {
        const error = new Error(`Stop delegated access sync. Some ms graph api calls failed`, {
          cause: foldersWithErrors,
        });
        this.logger.error(error);
        break;
      }
    }

    // Intentional: we flush the DB to the confirmed-accessible state even when a transient error
    // caused an early loop exit. This is safer than leaving stale access grants in place — the
    // next retry will re-confirm all folders and restore any that were missed.  If the very first
    // chunk fails (accessibleFolderIds is empty) all directories are removed; the subsequent
    // GenericRateLimitError will trigger a retry that rebuilds them from scratch.
    await this.db
      .delete(delegatedAccessDirectories)
      .where(
        and(
          eq(delegatedAccessDirectories.pipelineId, pipelineId),
          accessibleFolderIds.length > 0
            ? notInArray(delegatedAccessDirectories.directoryId, accessibleFolderIds)
            : undefined,
        ),
      );

    if (accessibleFolderIds.length > 0) {
      await this.db
        .insert(delegatedAccessDirectories)
        .values(
          accessibleFolderIds.map((directoryId) => ({
            pipelineId,
            directoryId,
          })),
        )
        .onConflictDoNothing();
    }

    const [result] = await this.db
      .select({ count: count() })
      .from(delegatedAccessDirectories)
      .where(eq(delegatedAccessDirectories.pipelineId, pipelineId));
    const dirCount = result?.count ?? 0;

    if (dirCount === 0 && !foldersWithErrors.length) {
      await this.db
        .delete(delegatedAccessPipelines)
        .where(eq(delegatedAccessPipelines.id, pipelineId));
      this.logger.log({ pipelineId, msg: 'No accessible directories, pipeline deleted' });
      return;
    }

    if (!foldersWithErrors.length) {
      await this.db
        .update(delegatedAccessPipelines)
        .set({ lastVerifiedAt: new Date() })
        .where(eq(delegatedAccessPipelines.id, pipelineId));
      this.logger.log({ pipelineId, dirCount, msg: 'Pipeline lastVerifiedAt updated' });
      return;
    }

    if (foldersWithErrors.some((error) => error.reason === 'transient-error')) {
      throw new GenericRateLimitError(`Delegated access sync failed because of rate limitting`, {
        cause: foldersWithErrors,
      });
    }

    throw new Error(`Delegated access sync failed with some errors`, {
      cause: foldersWithErrors,
    });
  }

  private async readAllFolders({
    client,
    ownerEmail,
  }: {
    client: Client;
    ownerEmail: string;
  }): Promise<string[]> {
    const fetchChildFolders = async (folderId: string): Promise<FolderNode[]> => {
      const children: FolderNode[] = [];
      let response = await client
        .api(`/users/${ownerEmail}/mailFolders/${folderId}/childFolders`)
        .top(500)
        .header('Prefer', 'IdType="ImmutableId"')
        .get();
      children.push(...(response?.value ?? []));

      while (response?.['@odata.nextLink']) {
        response = await client
          .api(response['@odata.nextLink'])
          .header('Prefer', 'IdType="ImmutableId"')
          .get();
        children.push(...(response?.value ?? []));
      }

      return children;
    };

    const limit = pLimit(10);
    const expandRecursive = async (folder: FolderNode): Promise<void> => {
      if (!folder.childFolderCount) {
        return;
      }

      folder.childFolders = await limit(() => fetchChildFolders(folder.id));
      await Promise.all(folder.childFolders.map(expandRecursive));
    };

    const rootFolders: FolderNode[] = [];
    let response = await client
      .api(`/users/${ownerEmail}/mailFolders`)
      .header('Prefer', 'IdType="ImmutableId"')
      .top(500)
      .get();
    rootFolders.push(...(response?.value ?? []));

    while (response?.['@odata.nextLink']) {
      response = await client
        .api(response['@odata.nextLink'])
        .header('Prefer', 'IdType="ImmutableId"')
        .get();
      rootFolders.push(...(response?.value ?? []));
    }

    await Promise.all(rootFolders.map(expandRecursive));

    const flattenFolders = (items: FolderNode[]): Array<string> =>
      items.flatMap((item) => [item.id, ...flattenFolders(item.childFolders ?? [])]);

    return flattenFolders(rootFolders);
  }
}
