import { createHash } from 'node:crypto';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, inArray, not, sql } from 'drizzle-orm';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, userProfiles } from '~/db';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { PersistentCacheService } from '../persistent-cache/persistent-cache.service';

export const SHARED_MAILBOX_SYNC_CACHE_KEY = 'SharedMailboxSync';
const CRON_JOB_NAME = 'shared-mailbox-sync';
const CRON_SCHEDULE = '0 0 * * 0';

interface GraphUser {
  id: string;
  mail: string | null;
  displayName: string | null;
}

@Injectable()
export class SharedMailboxSyncService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly persistentCacheService: PersistentCacheService,
    private readonly schedulerRegistry: SchedulerRegistry,
  ) {}

  public async onModuleInit(): Promise<void> {
    this.setupCronJob();
    await this.runIfHashChanged();
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
        await this.sync();
      } catch (err) {
        this.logger.error({ msg: 'Unexpected error during shared mailbox sync cron', err });
      }
    });
    this.schedulerRegistry.addCronJob(CRON_JOB_NAME, job);
    job.start();
  }

  private async runIfHashChanged(): Promise<void> {
    const sharedMailboxEmails = this.getSharedMailboxEmails();
    const currentHash = createHash('sha256').update(sharedMailboxEmails.join(',')).digest('hex');

    const cached = await this.persistentCacheService.get(
      SHARED_MAILBOX_SYNC_CACHE_KEY,
      `SharedMailboxSync`,
    );
    if (cached && cached.payload.envarHash === currentHash) {
      this.logger.log({ msg: 'SharedMailboxSync: env var unchanged, skipping startup sync' });
      return;
    }

    await this.sync();
  }

  public async sync(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping shared mailbox sync due to shutdown' });
      return;
    }

    this.logger.log({ msg: 'SharedMailboxSync: starting sync' });

    const envEmails = this.getSharedMailboxEmails();
    if (envEmails.length === 0) {
      this.logger.warn({ msg: 'SharedMailboxSync: SHARED_MAILBOXES env var is empty or unset' });
    }

    const client = await this.graphClientFactory.createClientForAnyAuthorizedUser();
    if (!client) {
      this.logger.warn({
        msg: 'SharedMailboxSync: no authorized user profile found, skipping sync',
      });
      return;
    }

    // Fetch disabled users from Graph (shared mailboxes are disabled accounts)
    let graphUsers: GraphUser[];
    try {
      graphUsers = await this.fetchDisabledUsersFromGraph(client);
    } catch (err) {
      if (
        err instanceof GraphError &&
        (err.statusCode === 429 || (err.statusCode >= 500 && err.statusCode < 600))
      ) {
        this.logger.error({
          msg: 'SharedMailboxSync: transient Graph error, skipping sync',
          statusCode: err.statusCode,
          err,
        });
        return;
      }
      throw err;
    }

    // Intersect Graph results with env var email list (case-insensitive)
    const matchedUsers = graphUsers.filter(
      (u) => u.mail && envEmails.includes(u.mail.toLowerCase()),
    ) as NonNullishProps<GraphUser, 'mail'>[];

    const matchedEmails = matchedUsers.map((u) => u.mail?.toLowerCase()).filter(Boolean);

    if (matchedUsers.length === 0 && envEmails.length > 0) {
      this.logger.warn({
        msg: 'SharedMailboxSync: no Graph users matched the configured shared mailbox emails',
        envEmails,
      });
    }

    // Delete source='shared-mailbox' rows whose email is NOT in the intersection
    if (matchedEmails.length > 0) {
      await this.db
        .delete(userProfiles)
        .where(
          and(
            eq(userProfiles.source, 'shared-mailbox'),
            not(inArray(sql`lower(${userProfiles.email})`, matchedEmails)),
          ),
        );
    } else {
      // No matches — delete all manual rows
      await this.db.delete(userProfiles).where(eq(userProfiles.source, 'shared-mailbox'));
    }

    // Upsert matched users
    if (matchedUsers.length > 0) {
      await this.db
        .insert(userProfiles)
        .values(
          matchedUsers.map((u) => ({
            provider: 'microsoft' as const,
            providerUserId: u.id,
            username: u.mail,
            email: u.mail,
            displayName: u.displayName ?? null,
            source: 'shared-mailbox' as const,
            accessToken: null,
            refreshToken: null,
          })),
        )
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
    const newHash = createHash('sha256').update(envEmails.join(',')).digest('hex');
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
}
