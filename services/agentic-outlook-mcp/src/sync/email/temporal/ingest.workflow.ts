import { proxyActivities } from '@temporalio/workflow';
import { serializeError } from 'serialize-error-cjs';
import { normalizeError } from '../../../utils/normalize-error';
import type {
  IEmbedActivity,
  IIndexActivity,
  IProcessActivity,
  IUpdateStatusActivity,
} from '../activities';

const { process } = proxyActivities<IProcessActivity>({
  startToCloseTimeout: '5 minutes',
  retry: {
    initialInterval: '1s',
    maximumInterval: '10m',
    backoffCoefficient: 2,
    maximumAttempts: 5,
  },
});

const { embed } = proxyActivities<IEmbedActivity>({
  startToCloseTimeout: '5 minutes',
  retry: {
    initialInterval: '1s',
    maximumInterval: '60s',
    backoffCoefficient: 2,
    maximumAttempts: 3,
  },
});

const { index } = proxyActivities<IIndexActivity>({
  startToCloseTimeout: '2 minutes',
  retry: {
    initialInterval: '1s',
    maximumInterval: '60s',
    backoffCoefficient: 2,
    maximumAttempts: 3,
  },
});

const { updateStatus } = proxyActivities<IUpdateStatusActivity>({
  startToCloseTimeout: '1 minute',
  retry: {
    initialInterval: '1s',
    maximumInterval: '30s',
    backoffCoefficient: 2,
    maximumAttempts: 3,
  },
});

export async function ingest(userProfileId: string, emailId: string): Promise<void> {
  try {
    await updateStatus({
      emailId,
    });

    await process({
      userProfileId,
      emailId,
    });

    await embed({
      userProfileId,
      emailId,
    });

    await index({
      userProfileId,
      emailId,
    });

    await updateStatus({
      emailId,
      completed: true,
    });
  } catch (error) {
    await updateStatus({
      emailId,
      error: serializeError(normalizeError(error)),
    });

    throw error;
  }
}
