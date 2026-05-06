import z from 'zod';

const DelegatedAccessVerificationCache = z.object({
  dataType: z.literal('DelegatedAccessVerification'),
  payload: z.object({
    state: z.enum(['running', 'failed', 'ready']),
    lastProcessedAccountsId: z.string().nullish(),
    lastProgressRegisteredAt: z.number(),
  }),
});

const DelegatedAccessDiscoveryCache = z.object({
  dataType: z.literal('DelegatedAccessDiscovery'),
  payload: z.object({
    state: z.enum(['running', 'failed', 'ready']),
    lastProcessedDelegateId: z.string().nullish(),
    lastProcessedOwnerIdForDelegate: z.string().nullish(),
    lastProgressRegisteredAt: z.number(),
  }),
});

export const cacheData = z.discriminatedUnion('dataType', [
  DelegatedAccessVerificationCache,
  DelegatedAccessDiscoveryCache,
]);

export type CacheData = z.infer<typeof cacheData>;
