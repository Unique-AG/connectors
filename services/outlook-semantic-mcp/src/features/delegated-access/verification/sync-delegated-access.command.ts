import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, count, eq, notInArray } from 'drizzle-orm';
import { chunk, pick } from 'remeda';
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
import { ReadOwnerMailboxFoldersFromMsGraphQuery } from '../commands/read-owner-mailbox-folders-for-delegated-access-verification.query';
import { TestReadAccessFromGraphEndpointQuery } from '../commands/test-read-access-from-graph-endpoint.query';
import {
  CannotReadErrorReason,
  DataAccessError,
  isDataAccessError,
} from '../utils/data-access-error';

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
    private readonly testReadAccessFromGraphEndpointQuery: TestReadAccessFromGraphEndpointQuery,
    private readonly readOwnerMailboxFoldersFromMsGraphQuery: ReadOwnerMailboxFoldersFromMsGraphQuery,
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
    if (this.config.scan !== 'granular_access') {
      this.logger.log({
        msg: `Skipped running delegated access verification. Reason: delegated access is not set to "granular_access"`,
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

    // If after directory updates there are no readable directories and during the verification there were no errors
    // we can safely remove this accounts pair because the current delegated user can only view directories inside
    // the owner mailbox but he cannot read data from any directory.
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
    return {
      status: 'failed',
      errors: dataAccessErrors.map((item) => pick(item, ['error', 'reason'])),
    };
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
    const testResult = await this.testReadAccessFromGraphEndpointQuery.run({
      client,
      endpoint: `/users/${ownerEmail}/messages`,
    });

    if (isDataAccessError(testResult)) {
      if (testResult.reason === CannotReadErrorReason.TokenExpired) {
        await onProgress?.();
      }
      return {
        hasFullDelegatedAccess: false,
        accessibleFolderIds: [],
        errors: [testResult],
      };
    }

    if (testResult.canRead) {
      await onProgress?.();
      return { hasFullDelegatedAccess: true };
    }

    if (verifyOnlyFullAccess) {
      return {
        hasFullDelegatedAccess: false,
        accessibleFolderIds: [],
        errors: [],
      };
    }

    const errors: DataAccessError[] = [];
    const fetchFoldersResult = await this.readOwnerMailboxFoldersFromMsGraphQuery.run({
      client,
      ownerEmail,
    });
    if (isDataAccessError(fetchFoldersResult)) {
      return {
        hasFullDelegatedAccess: false,
        accessibleFolderIds: [],
        errors: [fetchFoldersResult],
      };
    }
    if (!fetchFoldersResult.canRead || !fetchFoldersResult.folderIds.length) {
      return { hasFullDelegatedAccess: false, accessibleFolderIds: [], errors: [] };
    }

    const accessibleFolderIds: string[] = [];
    for (const folderIdsChunk of chunk(fetchFoldersResult.folderIds, 100)) {
      await Promise.all(
        folderIdsChunk.map(async (folderId): Promise<void> => {
          const verificationResult = await this.testReadAccessFromGraphEndpointQuery.run({
            client,
            endpoint: `/users/${ownerEmail}/mailFolders/${folderId}/messages`,
          });

          if (isDataAccessError(verificationResult)) {
            errors.push({ ...verificationResult, folderId });
            return;
          }

          await onProgress?.();
          if (verificationResult.canRead) {
            accessibleFolderIds.push(folderId);
          }
        }),
      );

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
}
