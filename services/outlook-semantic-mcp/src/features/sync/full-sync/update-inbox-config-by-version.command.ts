import { Inject, Injectable } from '@nestjs/common';
import { and, eq, SQL } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';

type InboxConfig = typeof inboxConfiguration.$inferSelect;

export type InboxConfigVersionedUpdate = Partial<{
  [K in Exclude<keyof InboxConfig, 'userProfileId' | 'fullSyncVersion'>]:
    | InboxConfig[K]
    | SQL<unknown>;
}>;

@Injectable()
export class UpdateInboxConfigByVersionCommand {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Span()
  public async run(
    userProfileId: string,
    version: string,
    values: InboxConfigVersionedUpdate,
  ): Promise<boolean> {
    const result = await this.db
      .update(inboxConfiguration)
      .set(values)
      .where(
        and(
          eq(inboxConfiguration.userProfileId, userProfileId),
          eq(inboxConfiguration.fullSyncVersion, version),
        ),
      )
      .execute();

    return (result.rowCount ?? 0) > 0;
  }
}
