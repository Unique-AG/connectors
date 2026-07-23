import { createHash } from 'node:crypto';
import { OAuthUserProfile } from '@unique-ag/mcp-oauth';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, inArray, isNull, not, sql } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import {
  DelegatedAccessConfig,
  delegatedAccessConfig,
  IngestionConfig,
  ingestionConfig,
  McpBackendType,
} from '~/config';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, userProfiles } from '~/db';
import { serializeMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { sleep } from '~/utils/sleep';
import { DeleteInboxDataCommand } from '../delete-inbox/delete-inbox-data.command';
import { PersistentCacheService } from '../persistent-cache/persistent-cache.service';
import { FullSyncEventDto } from '../sync/full-sync/full-sync-event.dto';

export const SHARED_MAILBOX_SYNC_CACHE_KEY = 'SharedMailboxSync';
const CRON_JOB_NAME = 'shared-mailbox-sync';

interface GraphUser {
  id: string;
  mail: string | null;
  displayName: string | null;
}

class FetchUsersError extends Error {
  public constructor(
    public readonly userId: string,
    message: string,
    options: ErrorOptions,
  ) {
    super(message, options);
  }
}

@Injectable()
export class SharedMailboxSyncService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;
  private syncIsRunning: boolean = false;

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(delegatedAccessConfig.KEY)
    private readonly config: DelegatedAccessConfig,
    @Inject(ingestionConfig.KEY)
    private readonly ingestionCfg: IngestionConfig,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly persistentCacheService: PersistentCacheService,
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly deleteInboxDataCommand: DeleteInboxDataCommand,
    private readonly amqp: AmqpConnection,
  ) {}

  public async onModuleInit(): Promise<void> {
    if (this.config.scan === 'disabled') {
      return;
    }
    // We only run the sync if the env var changed since our last run.
    if (await this.hasConfigChangedSinceLastSync()) {
      await this.runSyncWithRetries();
    } else {
      this.logger.log({
        msg: 'SharedMailboxSync: config unchanged since last sync, skipping startup sync',
      });
    }
    this.setupCronJob();
  }

  public onModuleDestroy(): void {
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob(CRON_JOB_NAME);
      job.stop();
    } catch (err) {
      this.logger.error({
        msg: 'Error stopping shared-mailbox-sync cron job',
        err,
      });
    }
  }

  private setupCronJob(): void {
    if (this.config.scan === 'disabled') {
      return;
    }
    // We need a cron job because once the mcp is setup we have no active user and we cannot sync the shared
    // mailboxes to database and we have to eighter login and restart the mcp or we can tell the client that
    // it takes at most until the next cron runs and there is a user which can list their ms graph users.
    // Since the mcp has in SCOPES User.Read.All all uses should have the permission to do this sync.
    const job = new CronJob(this.config.sharedMailboxSyncCronSchedule, async () => {
      try {
        await this.runSyncWithRetries();
      } catch (err) {
        this.logger.error({
          msg: 'Unexpected error during shared mailbox sync cron',
          err,
        });
      }
    });
    this.schedulerRegistry.addCronJob(CRON_JOB_NAME, job);
    job.start();
  }

  private async hasConfigChangedSinceLastSync(): Promise<boolean> {
    const cached = await this.persistentCacheService.get(
      SHARED_MAILBOX_SYNC_CACHE_KEY,
      'SharedMailboxSync',
    );
    if (!cached) {
      return true;
    }
    const currentHash = this.hashMailboxes(this.getSharedMailboxEmails());
    return cached.payload.envarHash !== currentHash;
  }

  private async runSyncWithRetries(): Promise<void> {
    if (this.syncIsRunning) {
      return;
    }
    this.syncIsRunning = true;
    const excludedUserIds: string[] = [];
    const backOffMs = 500;
    // We try to sync the shared mailboxes with the db up to 3 times, if we fail 3 times the cron will pick it up once we can find a user
    // which can actually do the sync.
    try {
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          await this.syncSharedMailboxesProfiles(excludedUserIds);
          break;
        } catch (err) {
          const { shouldRetry, excludeUserId } = this.handleSyncError(attempt, err);
          if (excludeUserId) {
            excludedUserIds.push(excludeUserId);
          }
          if (!shouldRetry) {
            break;
          }
          await sleep(backOffMs * 2 ** (attempt - 1));
        }
      }
    } finally {
      this.syncIsRunning = false;
    }
  }

  // Sync shared mailboxes will read the mailboxes from the env var will cross reference
  // them with msGraph api and save the common result to database.
  private async syncSharedMailboxesProfiles(excludedUserIds: string[]): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping shared mailbox sync due to shutdown' });
      return;
    }

    this.logger.log({ msg: 'SharedMailboxSync: starting sync' });

    const envEmails = this.getSharedMailboxEmails();
    if (envEmails.length === 0) {
      this.logger.warn({
        msg: 'SharedMailboxSync: DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS env var is empty or unset',
      });
    }

    // We group by email because the mcp in our QA handles 2 tenants, the unique prod and the dogfood tenant.
    const emailsByDomain = this.groupEmailsByDomain(envEmails);
    const allMatchedUsers: NonNullishProps<GraphUser, 'mail'>[] = [];
    const syncedDomains: string[] = [];

    for (const [domain, domainEmails] of emailsByDomain) {
      const result = await this.graphClientFactory.createClientForAnyAuthorizedUser(
        excludedUserIds,
        domain,
      );
      if (!result) {
        this.logger.warn({
          msg: 'SharedMailboxSync: no authorized user profile found for domain, skipping',
          domain,
        });
        continue;
      }
      const { client, userId } = result;

      let graphUsers: GraphUser[] = [];
      try {
        graphUsers = await this.fetchSharedMailboxCandidatesFromGraph(client);
        syncedDomains.push(domain);
      } catch (err) {
        if (err instanceof GraphError) {
          throw new FetchUsersError(userId, `Failed to fetch users from ms graph`, { cause: err });
        }
        throw err;
      }

      const matched = graphUsers
        .map((u) => ({ ...u, mail: u.mail?.toLowerCase() }))
        .filter((user) => user.mail && domainEmails.includes(user.mail)) as NonNullishProps<
        GraphUser,
        'mail'
      >[];

      if (matched.length === 0 && domainEmails.length > 0) {
        this.logger.warn({
          msg: 'SharedMailboxSync: no Graph users found for the configured shared mailbox emails',
          domain,
          domainEmails,
        });
      }

      allMatchedUsers.push(...matched);
    }

    const profilesToRemove = await this.db
      .select({ id: userProfiles.id })
      .from(userProfiles)
      .where(
        and(
          eq(userProfiles.source, 'shared-mailbox'),
          allMatchedUsers.length > 0
            ? not(
                inArray(
                  sql`lower(${userProfiles.email})`,
                  allMatchedUsers.map((item) => item.mail),
                ),
              )
            : undefined,
        ),
      );

    if (profilesToRemove.length > 0) {
      if (this.ingestionCfg.mcpBackend === McpBackendType.MicrosoftGraphAndUniqueApi) {
        for (const { id } of profilesToRemove) {
          const result = await this.deleteInboxDataCommand.run(id);
          this.logger.log({
            userProfileId: id,
            result,
            msg: 'SharedMailboxSync: triggered deletion for removed shared-mailbox profile',
          });
        }
      } else {
        await this.db.delete(userProfiles).where(
          inArray(
            userProfiles.id,
            profilesToRemove.map((p) => p.id),
          ),
        );
      }
    }

    // Upsert matched users
    if (allMatchedUsers.length > 0) {
      type UserProfileInsert = typeof userProfiles.$inferInsert;
      const mappedProfiles: UserProfileInsert[] = allMatchedUsers.map((user) => {
        const rawData: OAuthUserProfile = {
          id: user.id ?? undefined,
          displayName: user.displayName ?? undefined,
          username: user.mail ?? undefined,
          email: user.mail ?? undefined,
          avatarUrl: undefined,
          raw: user,
        };
        return {
          provider: 'microsoft' as const,
          providerUserId: user.id,
          username: user.mail,
          email: user.mail,
          displayName: user.displayName ?? null,
          source: 'shared-mailbox' as const,
          accessToken: null,
          refreshToken: null,
          raw: rawData,
        };
      });

      // source is intentionally omitted from the conflict update: if an Entra identity
      // already exists as an OAuth row we leave it as oauth. Overwriting source would
      // silently strip the user's own token-based access and subject them to delegate-only
      // logic, which is the wrong behaviour for a real user who also happens to be listed
      // as a shared mailbox.
      await this.db
        .insert(userProfiles)
        .values(mappedProfiles)
        .onConflictDoUpdate({
          target: [userProfiles.provider, userProfiles.providerUserId],
          set: {
            email: sql.raw(`excluded.${userProfiles.email.name}`),
            username: sql.raw(`excluded.${userProfiles.username.name}`),
            displayName: sql.raw(`excluded.${userProfiles.displayName.name}`),
          },
        })
        .returning({ id: userProfiles.id, source: userProfiles.source });

      if (this.ingestionCfg.mcpBackend === McpBackendType.MicrosoftGraphAndUniqueApi) {
        const ingestionCfg = this.ingestionCfg;

        // Query all shared-mailbox profiles that have no inbox configuration. This is broader than
        // filtering upsertedProfiles: it also catches profiles whose config was removed by an async
        // deletion triggered in a previous run. Profiles mid-deletion still have their config row
        // so they are naturally excluded by the LEFT JOIN / IS NULL predicate.
        const sharedMailboxesWithMissingInboxConfiguration = await this.db
          .select({ id: userProfiles.id })
          .from(userProfiles)
          .leftJoin(inboxConfigurations, eq(inboxConfigurations.userProfileId, userProfiles.id))
          .where(
            and(
              eq(userProfiles.source, 'shared-mailbox'),
              isNull(inboxConfigurations.userProfileId),
            ),
          );

        if (sharedMailboxesWithMissingInboxConfiguration.length > 0) {
          const insertedConfigs = await this.db
            .insert(inboxConfigurations)
            .values(
              sharedMailboxesWithMissingInboxConfiguration.map(
                (profile): typeof inboxConfigurations.$inferInsert => ({
                  userProfileId: profile.id,
                  fullSyncState: 'waiting-for-ingestion',
                  filters: serializeMailFilters(ingestionCfg.defaultMailFilters),
                }),
              ),
            )
            .onConflictDoNothing()
            .returning({ userProfileId: inboxConfigurations.userProfileId });

          for (const { userProfileId } of insertedConfigs) {
            const event = FullSyncEventDto.parse({
              type: 'unique.outlook-semantic-mcp.full-sync.retrigger',
              payload: { userProfileId },
            });
            await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
          }
        }
      }
    }

    // Only update the cache when every configured domain was successfully queried.
    // If some domains had no authorized user we leave the cache stale so the next
    // cron run retries them once a matching user logs in.
    if (syncedDomains.length === emailsByDomain.size) {
      const newHash = this.hashMailboxes(envEmails);
      await this.persistentCacheService.set(SHARED_MAILBOX_SYNC_CACHE_KEY, {
        dataType: 'SharedMailboxSync',
        payload: {
          envarHash: newHash,
          lastSyncedAt: Date.now(),
        },
      });
    }

    this.logger.log({
      msg: 'SharedMailboxSync: sync complete',
      upserted: allMatchedUsers.length,
      syncedDomains,
    });
  }

  private groupEmailsByDomain(emails: string[]): Map<string, string[]> {
    const map = new Map<string, string[]>();
    for (const email of emails) {
      const atIdx = email.lastIndexOf('@');
      if (atIdx === -1) {
        continue;
      }
      const domain = email.slice(atIdx + 1).toLowerCase();
      const existing = map.get(domain);
      if (existing) {
        existing.push(email);
      } else {
        map.set(domain, [email]);
      }
    }
    return map;
  }

  // The error handling here is very specific to the shared mailbox profile sync.
  private handleSyncError(
    attempt: number,
    err: unknown,
  ): { shouldRetry: boolean; excludeUserId?: string } {
    const msgBase = `Sync shared mailboxes failed, attempt: ${attempt}.`;
    // Only FetchUsersError is retryable — anything else (DB error, SDK bug, etc.) is unexpected
    // and we have no recovery strategy for it.
    if (!(err instanceof FetchUsersError)) {
      this.logger.error({
        msg: `${msgBase}. Error is not FetchUsersError. Sync will not be retried`,
        err,
      });
      return { shouldRetry: false };
    }
    const cause = err.cause;
    // This is a failsage guard FetchUsersError cause should always be graph error. If it's not we
    // have no retry strategy for this case.
    if (!(cause instanceof GraphError)) {
      this.logger.error({
        msg: `${msgBase}. Error is FetchUsersError cause is not GraphError. Sync will not be retried`,
        err,
      });
      return { shouldRetry: false };
    }

    // This should not happen unless token expired or the User.Read.All was added and the current logged in
    // users should login again to get a token with the new scoped - it is handled because it happened during
    // development.
    if (cause.statusCode === 401 || cause.statusCode === 403) {
      this.logger.log({
        msg: `${msgBase}. cause is GraphError, user has not enought permissions. Retrying with another user`,
        statusCode: cause.statusCode,
        err,
      });
      return { shouldRetry: true, excludeUserId: err.userId };
    }

    // This is a transient graph api error which we hope we can fix by waiting and retrying.
    if (cause.statusCode === 429 || (cause.statusCode >= 500 && cause.statusCode < 600)) {
      this.logger.log({
        msg: `${msgBase}. cause is GraphError, transient graph api error. Retrying with the same user`,
        statusCode: cause.statusCode,
        err,
      });
      return { shouldRetry: true };
    }

    // Unexpected Graph status (e.g. 400 Bad Request, 404 Not Found) — indicates a logic or
    // configuration problem that retrying with any user will not fix.
    this.logger.error({
      msg: `${msgBase}. cause is GraphError, unhandled status code`,
      statusCode: cause.statusCode,
      err,
    });
    return { shouldRetry: false };
  }

  private async fetchSharedMailboxCandidatesFromGraph(client: Client): Promise<GraphUser[]> {
    const users: GraphUser[] = [];

    // Shared mailboxes appear in Entra ID as accountEnabled=false accounts
    let response = (await client
      .api('/users')
      .select('id,mail,displayName')
      .top(500)
      .get()) as { value: GraphUser[]; '@odata.nextLink'?: string };

    users.push(...response.value);

    while (response['@odata.nextLink']) {
      response = (await client.api(response['@odata.nextLink']).get()) as {
        value: GraphUser[];
        '@odata.nextLink'?: string;
      };
      users.push(...response.value);
    }

    return users;
  }

  private getSharedMailboxEmails(): string[] {
    if (this.config.scan === 'disabled') {
      return [];
    }
    return this.config.sharedMailboxEmails;
  }

  private hashMailboxes(mailboxes: string[]): string {
    return `${this.config.mcpBackend}_${createHash('sha256')
      .update([...mailboxes].sort().join(','))
      .digest('hex')}`;
  }
}
