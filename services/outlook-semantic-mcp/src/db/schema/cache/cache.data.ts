import z from 'zod';

const DelegatedAccessVerificationCache = z.object({
  dataType: z.literal('DelegatedAccessVerification'),
  payload: z.object({
    state: z.enum(['running', 'failed', 'ready']),
    lastProcessedPipelineId: z.string().nullish(),
    lastProgressRegisteredAt: z.number(),
  }),
});

export const cacheData = z.discriminatedUnion('dataType', [DelegatedAccessVerificationCache]);

export type CacheData = z.infer<typeof cacheData>;
