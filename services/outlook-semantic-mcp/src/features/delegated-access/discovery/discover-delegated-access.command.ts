import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, gt, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { chunk } from 'remeda';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessPipeline,
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
    const connectedUsers = await this.db
      .select({ userProfileId: subscriptions.userProfileId, email: userProfiles.email })
      .from(subscriptions)
      .innerJoin(userProfiles, eq(subscriptions.userProfileId, userProfiles.id))
      .where(gt(subscriptions.expiresAt, sql`NOW()`))
      .groupBy(subscriptions.userProfileId, userProfiles.email);

    for (const { userProfileId: delegateUserId } of connectedUsers) {
      const owners = connectedUsers.filter((u) => u.userProfileId !== delegateUserId);
      const client = this.graphClientFactory.createClientForUser(delegateUserId);
      const batches = chunk(owners, 100);

      for (const batch of batches) {
        await Promise.all(
          batch.map(({ userProfileId: ownerUserId, email: ownerEmail }) => {
            return this.updateDelegatedAccess({ ownerUserId, ownerEmail, client, delegateUserId });
          }),
        );
      }
    }
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
        .insert(delegatedAccessPipeline)
        .values({
          delegateUserId,
          ownerUserId,
          lastDiscoveredAt: now,
        })
        .onConflictDoUpdate({
          target: [delegatedAccessPipeline.delegateUserId, delegatedAccessPipeline.ownerUserId],
          set: { lastDiscoveredAt: now },
        });

      this.logger.log({ delegateUserId, ownerUserId, msg: 'Delegated access discovered' });
    } catch (error) {
      if (error instanceof GraphError) {
        if (error.statusCode === 403 || error.statusCode === 404) {
          await this.db
            .delete(delegatedAccessPipeline)
            .where(
              and(
                eq(delegatedAccessPipeline.delegateUserId, delegateUserId),
                eq(delegatedAccessPipeline.ownerUserId, ownerUserId),
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
