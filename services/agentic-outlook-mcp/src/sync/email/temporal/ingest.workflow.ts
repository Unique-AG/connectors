import { proxyActivities } from '@temporalio/workflow';
import { serializeError } from 'serialize-error-cjs';
import { normalizeError } from '../../../utils/normalize-error';
import type { Activities } from '../activities';

interface IngestWorkflowParam {
  userProfileId: string;
  emailId: string;
}

const { loadEmail, saveEmailResults, createChunks, updateStatus, savePoints, index } =
  proxyActivities<
    Pick<
      Activities,
      'loadEmail' | 'saveEmailResults' | 'createChunks' | 'updateStatus' | 'savePoints' | 'index'
    >
  >({
    startToCloseTimeout: '1 minute',
    retry: {
      initialInterval: '1s',
      maximumInterval: '30s',
      backoffCoefficient: 2,
      maximumAttempts: 3,
    },
  });

const { cleanupEmail, translateEmail, summarizeBody, summarizeThread, embedDense } =
  proxyActivities<
    Pick<
      Activities,
      'cleanupEmail' | 'translateEmail' | 'summarizeBody' | 'summarizeThread' | 'embedDense'
    >
  >({
    startToCloseTimeout: '5 minutes',
    retry: {
      initialInterval: '1s',
      maximumInterval: '10m',
      backoffCoefficient: 2,
      maximumAttempts: 5,
    },
  });

const { embedSparse } = proxyActivities<Pick<Activities, 'embedSparse'>>({
  startToCloseTimeout: '5 minutes',
  taskQueue: 'python-queue',
  retry: {
    initialInterval: '1s',
    maximumInterval: '60s',
    backoffCoefficient: 2,
    maximumAttempts: 3,
  },
});

export async function ingest({ userProfileId, emailId }: IngestWorkflowParam): Promise<void> {
  try {
    await updateStatus({
      emailId,
    });

    const email = await loadEmail({
      userProfileId,
      emailId,
    });

    const { processedBody, language } = await cleanupEmail({
      email,
    });

    const { translatedBody, translatedSubject } = await translateEmail({
      emailId,
      subject: email.subject,
      processedBody: processedBody,
      language: language,
      translatedBody: email.translatedBody,
      translatedSubject: email.translatedSubject,
    });

    const { summarizedBody } = await summarizeBody({
      emailId,
      translatedBody: translatedBody,
      summarizedBody: email.summarizedBody,
    });

    const summarizedThreadResult = await summarizeThread({
      email,
    });

    const chunks = await createChunks({
      body: translatedBody,
    });

    const [densePoints, sparsePoints] = await Promise.all([
      embedDense({
        userProfileId,
        emailId,
        translatedSubject,
        translatedBody,
        summarizedBody,
        chunks,
      }),
      embedSparse({
        userProfileId,
        emailId,
        translatedSubject,
        translatedBody,
        summarizedBody,
        chunks,
      }),
    ]);

    await savePoints({
      userProfileId,
      emailId,
      points: [...densePoints, ...sparsePoints],
    });

    await saveEmailResults({
      userProfileId,
      emailId,
      updates: {
        processedBody: processedBody,
        language: language,
        translatedBody: translatedBody,
        translatedSubject: translatedSubject,
        summarizedBody: summarizedBody,
        threadSummary: summarizedThreadResult?.threadSummary,
      },
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
