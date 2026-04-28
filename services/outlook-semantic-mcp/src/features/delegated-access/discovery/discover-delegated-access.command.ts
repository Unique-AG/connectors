import { GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, gt, ne, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
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
  public async run(input: { delegateUserId: string }): Promise<void> {
    const { delegateUserId } = input;

    const connectedUsers = await this.db
      .select({ userProfileId: subscriptions.userProfileId, email: userProfiles.email })
      .from(subscriptions)
      .innerJoin(userProfiles, eq(subscriptions.userProfileId, userProfiles.id))
      .where(
        and(
          gt(subscriptions.expiresAt, sql`NOW()`),
          ne(subscriptions.userProfileId, delegateUserId),
        ),
      )
      .groupBy(subscriptions.userProfileId, userProfiles.email);

    const client = this.graphClientFactory.createClientForUser(delegateUserId);

    const BATCH_SIZE = 100;
    for (let i = 0; i < connectedUsers.length; i += BATCH_SIZE) {
      const batch = connectedUsers.slice(i, i + BATCH_SIZE);

      await Promise.all(
        batch.map(async ({ userProfileId: ownerUserId, email: ownerEmail }) => {
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
                target: [
                  delegatedAccessPipeline.delegateUserId,
                  delegatedAccessPipeline.ownerUserId,
                ],
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
        }),
      );
    }
  }
}
