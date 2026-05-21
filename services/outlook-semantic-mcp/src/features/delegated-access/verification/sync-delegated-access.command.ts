import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, count, eq, notInArray } from 'drizzle-orm';
import pLimit from 'p-limit';
import { chunk, isObjectType } from 'remeda';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessAccounts,
  delegatedAccessDirectories,
  userProfiles,
} from '~/db';
import { DelegatedAccessMetricsService } from '~/features/metrics/delegated-access-metrics.service';
import { NewTrace, traceAttrs } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { isTokenExpiredError } from '~/utils/is-token-expired-error';

interface FolderNode {
  id: string;
  childFolderCount: number;
  childFolders?: FolderNode[];
}

export enum CannotReadErrorReason {
  TokenExpired = 'token-expired',
  TransientError = 'transient-error',
  UnexpectedError = 'unexpected-error',
}

export interface DataAccessError {
  canRead: false;
  folderId?: string;
  reason: CannotReadErrorReason;
  error: unknown;
}

const isDataAccessError = (input: unknown): input is DataAccessError =>
  isObjectType(input) &&
  'reason' in input &&
  Object.values(CannotReadErrorReason).includes(input.reason as CannotReadErrorReason);

export type VerificationResult =
  | { status: 'success' }
  | { status: 'skipped' }
  | {
      status: 'failed';
      errors: {
        reason: CannotReadErrorReason;
        error: unknown;
      }[];
    };

@Injectable()
export class SyncDelegatedAccessCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
    private readonly metrics: DelegatedAccessMetricsService,
  ) {}

  @NewTrace('sync-delegated-access')
  public async run(input: {
    accountsId: string;
    onProgress?: () => Promise<void>;
  }): Promise<VerificationResult> {
    traceAttrs({ accountsId: input.accountsId });
    if (this.config.scan !== 'granularAccess') {
      this.logger.log({
        msg: `Skipped running delegated access verification. Reason: delegated access is not set to "granularAccess"`,
      });
      return { status: 'skipped' };
    }
    return await this.metrics.measureSyncRun(() =>
      this.runVerification(input.accountsId, input.onProgress),
    );
  }

  private async runVerification(
    accountsId: string,
    onProgress?: () => Promise<void>,
  ): Promise<VerificationResult> {
    const [accounts] = await this.db
      .select({
        delegateUserId: delegatedAccessAccounts.delegateUserId,
        ownerUserId: delegatedAccessAccounts.ownerUserId,
      })
      .from(delegatedAccessAccounts)
      .where(eq(delegatedAccessAccounts.id, accountsId));

    if (!accounts) {
      this.logger.warn({
        accountsId,
        msg: 'Accounts not found, skipping verification',
      });
      return { status: 'success' };
    }

    const { delegateUserId, ownerUserId } = accounts;

    const [ownerProfile] = await this.db
      .select({ email: userProfiles.email, source: userProfiles.source })
      .from(userProfiles)
      .where(eq(userProfiles.id, ownerUserId));

    const ownerEmail = ownerProfile?.email;
    if (!ownerEmail) {
      this.logger.warn({
        accountsId,
        ownerUserId,
        msg: 'Owner email not found, skipping verification',
      });
      return { status: 'success' };
    }

    const client = this.graphClientFactory.createClientForUser(delegateUserId);
    const verificationResult = await this.verifyReadAccess({
      client,
      ownerEmail,
      onProgress,
      verifyOnlyFullAccess: ownerProfile.source === 'shared-mailbox',
    });
    if (verificationResult.hasFullDelegatedAccess) {
      await this.db
        .delete(delegatedAccessDirectories)
        .where(eq(delegatedAccessDirectories.accountsId, accountsId));

      await this.db
        .update(delegatedAccessAccounts)
        .set({
          hasFullDelegatedAccess: true,
        })
        .where(eq(delegatedAccessAccounts.id, accountsId));
      return { status: 'success' };
    }

    const { accessibleFolderIds, errors: dataAccessErrors } = verificationResult;

    // Intentional: we flush the DB to the confirmed-accessible state even when a transient error
    // caused an early loop exit. This is safer than leaving stale access grants in place — the
    // next retry will re-confirm all folders and restore any that were missed.  If the very first
    // chunk fails (accessibleFolderIds is empty) all directories are removed; the subsequent
    // GenericRateLimitError will trigger a retry that rebuilds them from scratch.
    await this.db
      .delete(delegatedAccessDirectories)
      .where(
        and(
          eq(delegatedAccessDirectories.accountsId, accountsId),
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
            accountsId,
            directoryId,
          })),
        )
        .onConflictDoNothing();
    }

    const dirCount = await this.db
      .select({ count: count() })
      .from(delegatedAccessDirectories)
      .where(eq(delegatedAccessDirectories.accountsId, accountsId))
      .then((rows) => rows?.[0]?.count ?? 0);

    await this.db
      .update(delegatedAccessAccounts)
      .set({ hasFullDelegatedAccess: false })
      .where(eq(delegatedAccessAccounts.id, accountsId));

    if (dirCount === 0 && !dataAccessErrors.length) {
      await this.db
        .delete(delegatedAccessAccounts)
        .where(eq(delegatedAccessAccounts.id, accountsId));
      this.logger.log({
        accountsId,
        msg: 'No accessible directories, accounts deleted',
      });
      return { status: 'success' };
    }

    if (!dataAccessErrors.length) {
      await this.db
        .update(delegatedAccessAccounts)
        .set({ lastVerifiedAt: new Date() })
        .where(eq(delegatedAccessAccounts.id, accountsId));
      this.logger.log({ accountsId, dirCount, msg: 'Accounts lastVerifiedAt updated' });
      return { status: 'success' };
    }
    return { status: 'failed', errors: dataAccessErrors };
  }

  private async verifyReadAccess({
    client,
    ownerEmail,
    onProgress,
    verifyOnlyFullAccess,
  }: {
    client: Client;
    ownerEmail: string;
    onProgress?: () => Promise<void>;
    verifyOnlyFullAccess?: boolean;
  }): Promise<
    | { hasFullDelegatedAccess: true }
    | {
        hasFullDelegatedAccess: false;
        accessibleFolderIds: string[];
        errors: DataAccessError[];
      }
  > {
    const testResult = await this.testGraphEndpointForReadAccess({
      client,
      endpoint: `/users/${ownerEmail}/messages`,
    });

    if (testResult.canRead) {
      await onProgress?.();
      return { hasFullDelegatedAccess: true };
    }

    // We have no reason to run the folder tests the token expired
    if ('reason' in testResult && testResult.reason === CannotReadErrorReason.TokenExpired) {
      await onProgress?.();
      return {
        hasFullDelegatedAccess: false,
        accessibleFolderIds: [],
        errors: [testResult],
      };
    }

    if (verifyOnlyFullAccess) {
      return {
        hasFullDelegatedAccess: false,
        accessibleFolderIds: [],
        errors: [],
      };
    }

    const errors: DataAccessError[] = [];
    const folderIds = await this.readAllFolders({ client, ownerEmail });
    const accessibleFolderIds: string[] = [];
    for (const folderIdsChunk of chunk(folderIds, 100)) {
      const foldersWithAccessFetched = await Promise.all(
        folderIdsChunk.map(
          async (folderId): Promise<{ canRead: boolean; folderId: string } | DataAccessError> => {
            const verificationResult = await this.testGraphEndpointForReadAccess({
              client,
              endpoint: `/users/${ownerEmail}/mailFolders/${folderId}/messages`,
            });

            if (!isDataAccessError(verificationResult)) {
              await onProgress?.();
            }
            return { ...verificationResult, folderId };
          },
        ),
      );

      for (const item of foldersWithAccessFetched) {
        if (isDataAccessError(item)) {
          errors.push(item);
          continue;
        }

        if (item.canRead) {
          accessibleFolderIds.push(item.folderId);
        }
      }

      if (errors.length > 0) {
        const error = new Error(`Stop delegated access sync. Some ms graph api calls failed`, {
          cause: errors,
        });
        this.logger.error(error);
        break;
      }
    }
    return { hasFullDelegatedAccess: false, errors: errors, accessibleFolderIds };
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

  private async testGraphEndpointForReadAccess({
    client,
    endpoint,
  }: {
    client: Client;
    endpoint: string;
  }): Promise<Omit<DataAccessError, 'folderId'> | { canRead: true } | { canRead: false }> {
    try {
      await client.api(endpoint).select('id').top(1).get();
      return { canRead: true };
    } catch (error) {
      if (error instanceof GraphError) {
        if (error.code === 'MailboxInfoStale' || error.statusCode === 403 || error.statusCode === 404) {
          return { canRead: false };
        }
        if (isTokenExpiredError(error)) {
          return { canRead: false, reason: CannotReadErrorReason.TokenExpired, error };
        }
        if (error.statusCode === 429 || (error.statusCode >= 500 && error.statusCode < 600)) {
          return { canRead: false, reason: CannotReadErrorReason.TransientError, error };
        }
      }
      return { canRead: false, reason: CannotReadErrorReason.UnexpectedError, error };
    }
  }
}
