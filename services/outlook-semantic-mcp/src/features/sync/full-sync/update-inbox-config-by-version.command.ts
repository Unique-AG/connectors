import { Inject, Injectable } from '@nestjs/common';
import { and, eq, SQL } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations } from '~/db';

type InboxConfig = typeof inboxConfigurations.$inferSelect;

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
      .update(inboxConfigurations)
      .set(values)
      .where(
        and(
          eq(inboxConfigurations.userProfileId, userProfileId),
          eq(inboxConfigurations.fullSyncVersion, version),
        ),
      )
      .execute();

    return (result.rowCount ?? 0) > 0;
  }
}
