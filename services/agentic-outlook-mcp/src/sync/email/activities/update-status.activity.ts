import { Activities, Activity } from '@unique-ag/temporal';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, emails as emailsTable } from '../../../drizzle';

export interface IUpdateStatusActivity {
  updateStatus(payload: UpdateStatusPayload): Promise<void>;
}

interface UpdateStatusPayload {
  emailId: string;
  completed?: boolean;
  error?: Error;
}

@Injectable()
@Activities()
export class UpdateStatusActivity {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Activity()
  public async updateStatus(payload: UpdateStatusPayload): Promise<void> {
    const updateData: Record<string, string> = {
      ingestionLastAttemptAt: new Date().toISOString(),
    };

    if (payload.completed) updateData.ingestionCompletedAt = new Date().toISOString();
    if (payload.error) updateData.ingestionLastError = JSON.stringify(payload.error);

    await this.db.update(emailsTable).set(updateData).where(eq(emailsTable.id, payload.emailId));
  }
}
