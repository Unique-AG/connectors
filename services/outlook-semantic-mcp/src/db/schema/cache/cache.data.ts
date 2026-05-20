import z from 'zod';

const DelegatedAccessVerificationCache = z.object({
  dataType: z.literal('DelegatedAccessVerification'),
  payload: z.object({
    state: z.enum(['running', 'failed', 'ready']),
    lastProcessedAccountsId: z.string().nullish(),
    lastProgressRegisteredAt: z.number(),
  }),
});

export type DelegatedAccessVerificationCacheType = z.infer<typeof DelegatedAccessVerificationCache>;

const DelegatedAccessDiscoveryCache = z.object({
  dataType: z.literal('DelegatedAccessDiscovery'),
  payload: z.object({
    state: z.enum(['running', 'failed', 'ready']),
    lastProcessedDelegateId: z.string().nullish(),
    lastProcessedOwnerIdForDelegate: z.string().nullish(),
    lastProgressRegisteredAt: z.number(),
  }),
});

export type DelegatedAccessDiscoveryCacheType = z.infer<typeof DelegatedAccessDiscoveryCache>;

const SharedMailboxSyncCache = z.object({
  dataType: z.literal('SharedMailboxSync'),
  payload: z.object({
    envarHash: z.string(),
    lastSyncedAt: z.number(),
  }),
});

export type SharedMailboxSyncCacheType = z.infer<typeof SharedMailboxSyncCache>;

export const cacheData = z.discriminatedUnion('dataType', [
  DelegatedAccessVerificationCache,
  DelegatedAccessDiscoveryCache,
  SharedMailboxSyncCache,
]);

export type CacheData = z.infer<typeof cacheData>;

// biome-ignore format: flat conditional chain is easier to read than biome's nested indentation
export type GetCacheDataByType<T extends CacheData['dataType']> =
  T extends SharedMailboxSyncCacheType['dataType'] ? SharedMailboxSyncCacheType :
  T extends DelegatedAccessDiscoveryCacheType['dataType'] ? DelegatedAccessDiscoveryCacheType :
  T extends DelegatedAccessVerificationCacheType['dataType'] ? DelegatedAccessVerificationCacheType
  : unknown;

export function isCacheDataOfType<T extends CacheData['dataType']>(
  t: CacheData,
  type: T,
): t is GetCacheDataByType<T> {
  return t.dataType === type;
}
