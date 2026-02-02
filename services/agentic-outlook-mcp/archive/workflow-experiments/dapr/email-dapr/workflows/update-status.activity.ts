import { WorkflowActivityContext, WorkflowRuntime } from '@dapr/dapr';
import { Inject, Injectable, OnModuleInit } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import {
  DRIZZLE,
  DrizzleDatabase,
  emails as emailsTable,
  IngestionStatus,
  ingestionStatusEnum,
} from '../../../drizzle';

interface UpdateStatusPayload {
  emailId: string;
  status: IngestionStatus;
  error?: string;
}

@Injectable()
export class UpdateStatusActivity implements OnModuleInit {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly runtime: WorkflowRuntime,
  ) {}

  public async onModuleInit() {
    const updateStatus = async (_ctx: WorkflowActivityContext, payload: UpdateStatusPayload) => {
      return this.updateStatus(payload);
    };
    this.runtime.registerActivity(updateStatus);
  }

  public updateStatus(payload: UpdateStatusPayload) {
    if (payload.error && payload.status !== ingestionStatusEnum.enum.failed)
      throw new Error('Error cannot be set for non-failed status');
    if (payload.status === ingestionStatusEnum.enum.failed && !payload.error)
      throw new Error('Error must be set for failed status');

    return payload.error
      ? this.db
          .update(emailsTable)
          .set({
            ingestionStatus: ingestionStatusEnum.enum.failed,
            ingestionLastAttemptAt: new Date().toISOString(),
            ingestionLastError: payload.error,
            ingestionCompletedAt: new Date().toISOString(),
          })
          .where(eq(emailsTable.id, payload.emailId))
      : this.db
          .update(emailsTable)
          .set({
            ingestionStatus: payload.status,
            ingestionLastAttemptAt: new Date().toISOString(),
          })
          .where(eq(emailsTable.id, payload.emailId));
  }
}
