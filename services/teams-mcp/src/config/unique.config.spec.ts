import { describe, expect, it } from 'vitest';
import { UniqueConfigSchema } from './unique.config';

const clusterLocal = (apiKey?: string) => ({
  integration: 'enabled',
  serviceAuthMode: 'cluster_local',
  apiBaseUrl: 'https://node-chat.finance-gpt.svc.cluster.local:8092/public/',
  rootScopeId: 'scope_root_01',
  ingestionServiceBaseUrl: 'https://node-ingestion.finance-gpt.svc.cluster.local/',
  serviceExtraHeaders: JSON.stringify({
    'x-user-id': 'user_01',
    'x-company-id': 'company_01',
  }),
  ...(apiKey === undefined ? {} : { apiKey }),
});

describe('UniqueConfigSchema apiKey', () => {
  it('accepts a generated Unique API key', () => {
    const result = UniqueConfigSchema.safeParse(clusterLocal('ukey_j-frejgnegAB_09'));

    expect(result.success).toBe(true);
  });

  it('rejects a key containing a dot, which the Unique API would misread as a JWT', () => {
    const result = UniqueConfigSchema.safeParse(clusterLocal('ukey_abc.def'));

    expect(result.success).toBe(false);
  });

  it('stays optional so deployments without a key still boot', () => {
    const result = UniqueConfigSchema.safeParse(clusterLocal());

    expect(result.success).toBe(true);
  });
});
