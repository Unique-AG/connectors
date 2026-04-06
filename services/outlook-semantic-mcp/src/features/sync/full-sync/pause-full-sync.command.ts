import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, inArray } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations } from '~/db';

type PauseResult =
  | { status: 'paused' }
  | { status: 'not-found' }
  | { status: 'invalid-state'; currentState: string };

const PAUSABLE_STATES = ['running', 'waiting-for-ingestion'] as const;

@Injectable()
export class PauseFullSyncCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Span()
  public async run(userProfileId: string): Promise<PauseResult> {
    const result = await this.db
      .update(inboxConfigurations)
      .set({ fullSyncState: 'paused' })
      .where(
        and(
          eq(inboxConfigurations.userProfileId, userProfileId),
          inArray(inboxConfigurations.fullSyncState, [...PAUSABLE_STATES]),
        ),
      )
      .execute();

    if ((result.rowCount ?? 0) > 0) {
      this.logger.log({ userProfileId, msg: 'Full sync paused' });
      return { status: 'paused' };
    }

    const config = await this.db.query.inboxConfigurations.findFirst({
      where: eq(inboxConfigurations.userProfileId, userProfileId),
    });

    if (!config) {
      return { status: 'not-found' };
    }

    return { status: 'invalid-state', currentState: config.fullSyncState };
  }
}
