import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations } from '~/db';

export const INBOX_DELETION_IN_PROGRESS_MESSAGE =
  'Inbox deletion is in progress. Please wait until deletion completes before performing this action.';

@Injectable()
export class IsInboxDeletingQuery {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async run(userProfileId: string): Promise<boolean> {
    const row = await this.db
      .select({ deletingInboxStartedAt: inboxConfigurations.deletingInboxStartedAt })
      .from(inboxConfigurations)
      .where(eq(inboxConfigurations.userProfileId, userProfileId))
      .then((rows) => rows[0]);

    return row?.deletingInboxStartedAt != null;
  }
}
