import { TWorkflow, WorkflowContext } from '@dapr/dapr';
import { Logger } from '@nestjs/common';
import { serializeError } from 'serialize-error-cjs';
import { ingestionStatusEnum } from '../../../drizzle';
import { normalizeError } from '../../../utils/normalize-error';

interface IngestPayload {
  userProfileId: string;
  emailId: string;
}

export const ingestWorkflow: TWorkflow = async function* ingestWorkflow(
  ctx: WorkflowContext,
  { userProfileId, emailId }: IngestPayload,
) {
  const logger = new Logger('IngestWorkflow');
  const workflowId = ctx.getWorkflowInstanceId();
  logger.log(`Ingest workflow started for workflow ${workflowId}`);

  yield ctx.callActivity('updateStatus', {
    emailId,
    status: ingestionStatusEnum.enum.pending,
  });

  try {
    yield ctx.callActivity('process', {
      userProfileId,
      emailId,
    });

    yield ctx.callActivity('updateStatus', {
      emailId,
      status: ingestionStatusEnum.enum.processed,
    });

    yield ctx.callActivity('embed', {
      userProfileId,
      emailId,
    });

    yield ctx.callActivity('updateStatus', {
      emailId,
      status: ingestionStatusEnum.enum['densely-embedded'],
    });

    yield ctx.callActivity('index', {
      userProfileId,
      emailId,
    });

    yield ctx.callActivity('updateStatus', {
      emailId,
      status: ingestionStatusEnum.enum.completed,
    });
  } catch (error) {
    logger.error(`Ingest workflow failed for workflow ${workflowId}`, error);
    yield ctx.callActivity('updateStatus', {
      emailId,
      status: ingestionStatusEnum.enum.failed,
      error: serializeError(normalizeError(error)),
    });
  }
  logger.log(`Ingest workflow completed for workflow ${workflowId}`);
};
