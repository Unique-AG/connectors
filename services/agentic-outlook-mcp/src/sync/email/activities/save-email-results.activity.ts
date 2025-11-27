import { Activities, Activity } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Context } from '@temporalio/activity';
import { and, eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, emails as emailsTable } from '../../../drizzle';

export interface ISaveEmailResultsActivity {
  saveEmailResults(payload: SaveEmailResultsPayload): Promise<void>;
}

interface SaveEmailResultsPayload {
  userProfileId: string;
  emailId: string;
  updates: {
    processedBody?: string;
    language?: string;
    translatedBody?: string;
    translatedSubject?: string | null;
    summarizedBody?: string;
    threadSummary?: string;
  };
}

@Injectable()
@Activities()
export class SaveEmailResultsActivity implements ISaveEmailResultsActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Activity()
  public async saveEmailResults({
    userProfileId,
    emailId,
    updates,
  }: SaveEmailResultsPayload): Promise<void> {
    const contextInfo = Context.current().info;

    this.logger.debug({
      msg: 'Saving email results',
      emailId: emailId,
      userProfileId: userProfileId,
      updates: Object.keys(updates),
      attempt: contextInfo.attempt,
    });

    if (Object.keys(updates).length === 0) {
      this.logger.log({
        msg: 'No updates to save',
        emailId: emailId,
        userProfileId: userProfileId,
      });
      return;
    }

    await this.db
      .update(emailsTable)
      .set(updates)
      .where(and(eq(emailsTable.id, emailId), eq(emailsTable.userProfileId, userProfileId)));

    this.logger.debug({
      msg: 'Email results saved',
      emailId: emailId,
      userProfileId: userProfileId,
    });
  }
}

