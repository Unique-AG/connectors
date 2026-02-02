import { Activities, Activity } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Context } from '@temporalio/activity';
import { and, eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, Email, emails as emailsTable } from '../../../drizzle';

export interface ILoadEmailActivity {
  loadEmail(payload: LoadEmailPayload): Promise<Email>;
}

interface LoadEmailPayload {
  userProfileId: string;
  emailId: string;
}

@Injectable()
@Activities()
export class LoadEmailActivity implements ILoadEmailActivity {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Activity()
  public async loadEmail({ userProfileId, emailId }: LoadEmailPayload): Promise<Email> {
    const contextInfo = Context.current().info;

    this.logger.debug({
      msg: 'Loading email',
      emailId: emailId,
      userProfileId: userProfileId,
      attempt: contextInfo.attempt,
    });

    const email = await this.db.query.emails.findFirst({
      where: and(eq(emailsTable.id, emailId), eq(emailsTable.userProfileId, userProfileId)),
    });

    if (!email) throw new Error('Email not found');

    this.logger.debug({
      msg: 'Email loaded',
      emailId: emailId,
      userProfileId: userProfileId,
    });

    return email;
  }
}
