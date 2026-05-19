import { createHash } from 'node:crypto';
import { OAuthUserProfile } from '@unique-ag/mcp-oauth';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, inArray, not, sql } from 'drizzle-orm';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, userProfiles } from '~/db';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { sleep } from '~/utils/sleep';
import { PersistentCacheService } from '../persistent-cache/persistent-cache.service';

export const SHARED_MAILBOX_SYNC_CACHE_KEY = 'SharedMailboxSync';
const CRON_JOB_NAME = 'shared-mailbox-sync';
const CRON_SCHEDULE = '* * * * *';

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
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly persistentCacheService: PersistentCacheService,
    private readonly schedulerRegistry: SchedulerRegistry,
  ) {}

  public async onModuleInit(): Promise<void> {
    // On startup we run it just in case anything changed in ms graph api.
    await this.runSyncWithRetries();
    this.setupCronJob();
  }

  public onModuleDestroy(): void {
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob(CRON_JOB_NAME);
      job.stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping shared-mailbox-sync cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(CRON_SCHEDULE, async () => {
      try {
        await this.runSyncWithRetries();
      } catch (err) {
        this.logger.error({ msg: 'Unexpected error during shared mailbox sync cron', err });
      }
    });
    this.schedulerRegistry.addCronJob(CRON_JOB_NAME, job);
    job.start();
  }

  private async runSyncWithRetries(): Promise<void> {
    if (this.syncIsRunning) {
      return;
    }
    this.syncIsRunning = true;
    const excludedUserIds: string[] = [];
    const handleGraphError = (attempt: number, err: unknown): { shouldRetry: boolean } => {
      const msgBase = `Sync shared mailboxes failed, attempt: ${attempt}.`;
      if (!(err instanceof FetchUsersError)) {
        this.logger.error({
          msg: `${msgBase}. Error is not FetchUsersError. Sync will not be retried`,
          err,
        });
        return { shouldRetry: false };
      }
      const cause = err.cause;
      if (!(cause instanceof GraphError)) {
        this.logger.error({
          msg: `${msgBase}. Error is FetchUsersError cause is not GraphError. Sync will not be retried`,
          err,
        });
        return { shouldRetry: false };
      }

      if (cause.statusCode === 401 || cause.statusCode === 403) {
        this.logger.log({
          msg: `${msgBase}. cause is GraphError, user has not enought permissions. Retrying with another user`,
          statusCode: cause.statusCode,
          err,
        });
        excludedUserIds.push(err.userId);
        return { shouldRetry: true };
      }

      if (cause.statusCode === 429 || (cause.statusCode >= 500 && cause.statusCode < 600)) {
        this.logger.log({
          msg: `${msgBase}. cause is GraphError, transient graph api error. Retrying with the same user`,
          statusCode: cause.statusCode,
          err,
        });
        return { shouldRetry: true };
      }

      this.logger.error({
        msg: `${msgBase}. cause is GraphError, unhandled status code`,
        statusCode: cause.statusCode,
        err,
      });
      return { shouldRetry: false };
    };

    const backOffMs = 500;
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        await this.sync(excludedUserIds);
        break;
      } catch (err) {
        const { shouldRetry } = handleGraphError(attempt, err);
        if (!shouldRetry) {
          break;
        }
        await sleep(backOffMs * 2 ** (attempt - 1));
      }
    }
    this.syncIsRunning = false;
  }

  private async sync(excludedUserIds: string[]): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping shared mailbox sync due to shutdown' });
      return;
    }

    this.logger.log({ msg: 'SharedMailboxSync: starting sync' });

    const envEmails = this.getSharedMailboxEmails();
    if (envEmails.length === 0) {
      this.logger.warn({ msg: 'SharedMailboxSync: SHARED_MAILBOXES env var is empty or unset' });
    }

    const result = await this.graphClientFactory.createClientForAnyAuthorizedUser(excludedUserIds);
    if (!result) {
      this.logger.warn({
        msg: 'SharedMailboxSync: no authorized user profile found, skipping sync',
      });
      return;
    }
    const { client, userId } = result;

    let graphUsers: GraphUser[] = [];
    try {
      graphUsers = await this.fetchDisabledUsersFromGraph(client);
    } catch (err) {
      throw new FetchUsersError(userId, `Failed to fetch users from ms graph`, { cause: err });
    }

    const matchedUsers = graphUsers.filter((u) => u.mail) as NonNullishProps<GraphUser, 'mail'>[];
    const matchedEmails = matchedUsers.map((u) => u.mail.toLowerCase());

    if (matchedUsers.length === 0 && envEmails.length > 0) {
      this.logger.warn({
        msg: 'SharedMailboxSync: no Graph users found for the configured shared mailbox emails',
        envEmails,
      });
    }

    // Delete source='shared-mailbox' rows whose email is NOT in the intersection
    await this.db
      .delete(userProfiles)
      .where(
        and(
          eq(userProfiles.source, 'shared-mailbox'),
          matchedEmails.length > 0
            ? not(inArray(sql`lower(${userProfiles.email})`, matchedEmails))
            : undefined,
        ),
      );

    // Upsert matched users
    if (matchedUsers.length > 0) {
      type UserProfileInsert = typeof userProfiles.$inferInsert;
      const mappedProfiles: UserProfileInsert[] = matchedUsers.map((user) => {
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

      await this.db
        .insert(userProfiles)
        .values(mappedProfiles)
        .onConflictDoUpdate({
          target: [userProfiles.provider, userProfiles.providerUserId],
          set: {
            email: sql`excluded.email`,
            username: sql`excluded.username`,
            displayName: sql`excluded.display_name`,
          },
        });
    }

    // Update cache with new hash and timestamp
    const newHash = this.hashMailboxes(envEmails);
    await this.persistentCacheService.set(SHARED_MAILBOX_SYNC_CACHE_KEY, {
      dataType: 'SharedMailboxSync',
      payload: {
        envarHash: newHash,
        lastSyncedAt: Date.now(),
      },
    });

    this.logger.log({
      msg: 'SharedMailboxSync: sync complete',
      upserted: matchedUsers.length,
    });
  }

  private getSharedMailboxEmails(): string[] {
    if (this.config.scan === 'disabled') {
      return [];
    }
    return this.config.sharedMailboxEmails;
  }

  private async fetchDisabledUsersFromGraph(client: Client): Promise<GraphUser[]> {
    const users: GraphUser[] = [];

    let response = (await client
      .api('/users')
      .filter('accountEnabled eq false')
      .select('id,mail,displayName')
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

  private hashMailboxes(mailboxes: string[]): string {
    return createHash('sha256').update(mailboxes.sort().join(',')).digest('hex');
  }
}
