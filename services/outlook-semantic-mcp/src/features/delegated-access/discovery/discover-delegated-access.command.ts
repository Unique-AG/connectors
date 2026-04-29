import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, gt, inArray, isNotNull, notInArray, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { last } from 'remeda';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessPipelines,
  subscriptions,
  userProfiles,
} from '~/db';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

@Injectable()
export class DiscoverDelegatedAccessCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run(): Promise<void> {
    let lastProcessedUserId: string | undefined;
    let usersBatch = await this.fetchBatch({});

    while (usersBatch.length) {
      for (const { userProfileId: delegateUserId } of usersBatch) {
        const client = this.graphClientFactory.createClientForUser(delegateUserId);
        let ownersLastFetchedId: string | undefined;
        let ownersBatch = await this.fetchBatch({
          lastFetchedId: ownersLastFetchedId,
          excludedProfileIds: [delegateUserId],
        });

        while (ownersBatch.length) {
          await Promise.all(
            ownersBatch.map(({ userProfileId: ownerUserId, email: ownerEmail }) => {
              return this.updateDelegatedAccess({
                ownerUserId,
                ownerEmail,
                client,
                delegateUserId,
              });
            }),
          );

          ownersLastFetchedId = last(ownersBatch)?.userProfileId;
          ownersBatch = await this.fetchBatch({
            lastFetchedId: ownersLastFetchedId,
            excludedProfileIds: [delegateUserId],
          });
        }
      }

      lastProcessedUserId = last(usersBatch)?.userProfileId;
      usersBatch = await this.fetchBatch({ lastFetchedId: lastProcessedUserId });
    }
  }

  private async fetchBatch({
    lastFetchedId,
    excludedProfileIds,
  }: {
    lastFetchedId?: string;
    excludedProfileIds?: string[];
  }): Promise<{ userProfileId: string; email: string }[]> {
    const activeSubscriptions = this.db
      .select({ userProfileId: subscriptions.userProfileId })
      .from(subscriptions)
      .where(and(gt(subscriptions.expiresAt, sql`NOW()`)));

    const items = await this.db
      .select({ userProfileId: userProfiles.id, email: userProfiles.email })
      .from(userProfiles)
      .where(
        and(
          lastFetchedId ? gt(userProfiles.id, lastFetchedId) : undefined,
          isNotNull(userProfiles.email),
          excludedProfileIds && excludedProfileIds.length > 0
            ? notInArray(userProfiles.id, excludedProfileIds)
            : undefined,
          inArray(userProfiles.id, activeSubscriptions),
        ),
      )
      .orderBy(userProfiles.id)
      .limit(100);

    // Type casting is safe because isNotNull(userProfiles.email) ensures the email is not null
    return items as { userProfileId: string; email: string }[];
  }

  private async updateDelegatedAccess({
    ownerEmail,
    delegateUserId,
    ownerUserId,
    client,
  }: {
    client: Client;
    delegateUserId: string;
    ownerUserId: string;
    ownerEmail: string | null;
  }): Promise<void> {
    if (!ownerEmail) {
      this.logger.warn({ ownerUserId, msg: 'Skipping owner with null email' });
      return;
    }

    try {
      await client.api(`/users/${ownerEmail}/mailFolders`).top(1).get();

      const now = new Date();
      await this.db
        .insert(delegatedAccessPipelines)
        .values({
          delegateUserId,
          ownerUserId,
          lastDiscoveredAt: now,
        })
        .onConflictDoUpdate({
          target: [delegatedAccessPipelines.delegateUserId, delegatedAccessPipelines.ownerUserId],
          set: { lastDiscoveredAt: now },
        });

      this.logger.log({ delegateUserId, ownerUserId, msg: 'Delegated access discovered' });
    } catch (error) {
      if (error instanceof GraphError) {
        if (error.statusCode === 403 || error.statusCode === 404) {
          await this.db
            .delete(delegatedAccessPipelines)
            .where(
              and(
                eq(delegatedAccessPipelines.delegateUserId, delegateUserId),
                eq(delegatedAccessPipelines.ownerUserId, ownerUserId),
              ),
            );
          this.logger.log({
            delegateUserId,
            ownerUserId,
            statusCode: error.statusCode,
            msg: 'Delegated access revoked, removed from pipeline',
          });
          return;
        }

        if (error.statusCode === 429 || (error.statusCode >= 500 && error.statusCode < 600)) {
          this.logger.warn({
            delegateUserId,
            ownerUserId,
            statusCode: error.statusCode,
            msg: 'Transient error during discovery, skipping',
          });
          return;
        }
      }

      this.logger.error({
        delegateUserId,
        ownerUserId,
        error,
        msg: 'Unexpected error during delegated access discovery',
      });
    }
  }
}
