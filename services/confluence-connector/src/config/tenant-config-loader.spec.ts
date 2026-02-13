import assert from 'node:assert';
import { dump } from 'js-yaml';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthMode } from './confluence.schema';

vi.mock('node:fs', () => ({
  globSync: vi.fn(),
  readFileSync: vi.fn(),
}));

const CONFIG_PATH = '/config/tenant.yaml';
const CONFIG_PATH_2 = '/config/tenant2.yaml';

const baseProcessingConfig = {
  stepTimeoutSeconds: 300,
  concurrency: 1,
  scanIntervalCron: '*/15 * * * *',
};

const clusterLocalUniqueConfig = {
  serviceAuthMode: 'cluster_local',
  serviceExtraHeaders: {
    'x-company-id': 'test-company',
    'x-user-id': 'test-user',
  },
  ingestionServiceBaseUrl: 'http://ingestion:8091',
  scopeManagementServiceBaseUrl: 'http://scope:8094',
  apiRateLimitPerMinute: 100,
};

const externalUniqueConfigWithoutSecret = {
  serviceAuthMode: 'external',
  zitadelOauthTokenUrl: 'https://idp.unique.app/oauth/v2/token',
  zitadelProjectId: 'test-project-id',
  zitadelClientId: 'test-client-id',
  ingestionServiceBaseUrl: 'https://api.unique.app/ingestion',
  scopeManagementServiceBaseUrl: 'https://api.unique.app/scope-management',
  apiRateLimitPerMinute: 100,
};

const baseConfluenceFields = {
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'ai-ingest',
  ingestAllLabel: 'ai-ingest-all',
};

const oauth2loAuth = {
  mode: AuthMode.OAUTH_2LO,
  clientId: 'test-client-id',
};

const patAuth = {
  mode: AuthMode.PAT,
};

function assertFirstElement<T>(arr: T[]): T {
  const item = arr[0];
  assert.ok(item !== undefined, 'Expected at least one element');
  return item;
}

describe('tenant-config-loader', () => {
  const envKeysToClean = [
    'TENANT_CONFIG_PATH_PATTERN',
    'CONFLUENCE_CLIENT_SECRET',
    'CONFLUENCE_PAT',
    'ZITADEL_CLIENT_SECRET',
    'LOGS_DIAGNOSTICS_DATA_POLICY',
  ] as const;

  const envBackup: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of envKeysToClean) {
      envBackup[key] = process.env[key];
    }
    process.env.TENANT_CONFIG_PATH_PATTERN = '/config/*.yaml';
    delete process.env.CONFLUENCE_CLIENT_SECRET;
    delete process.env.CONFLUENCE_PAT;
    delete process.env.ZITADEL_CLIENT_SECRET;
  });

  afterEach(() => {
    for (const key of envKeysToClean) {
      if (envBackup[key] === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = envBackup[key];
      }
    }
    vi.restoreAllMocks();
  });

  async function loadModule() {
    vi.resetModules();
    const fs = await import('node:fs');
    const mod = await import('./tenant-config-loader');
    return { globSync: vi.mocked(fs.globSync), readFileSync: vi.mocked(fs.readFileSync), ...mod };
  }

  function setupFsMocks(
    globSync: ReturnType<typeof vi.fn>,
    readFileSync: ReturnType<typeof vi.fn>,
    configs: { path: string; config: Record<string, unknown> }[],
  ) {
    globSync.mockReturnValue(configs.map((c) => c.path));
    readFileSync.mockImplementation((filePath: unknown) => {
      const match = configs.find((c) => c.path === filePath);
      if (!match) throw new Error(`Unexpected file path: ${filePath}`);
      return dump(match.config);
    });
  }

  function setupSingleConfig(
    globSync: ReturnType<typeof vi.fn>,
    readFileSync: ReturnType<typeof vi.fn>,
    config: Record<string, unknown>,
  ) {
    setupFsMocks(globSync, readFileSync, [{ path: CONFIG_PATH, config }]);
  }

  describe('valid config loading', () => {
    it('loads cloud config with oauth_2lo auth', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';

      const cloudConfig = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, cloudConfig);

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      const tenant = assertFirstElement(result);
      expect(tenant.confluence.instanceType).toBe('cloud');
      expect(tenant.confluence.baseUrl).toBe('https://acme.atlassian.net/wiki');
      expect(tenant.confluence.auth.mode).toBe(AuthMode.OAUTH_2LO);
      const auth = tenant.confluence.auth as Extract<
        typeof tenant.confluence.auth,
        { mode: typeof AuthMode.OAUTH_2LO }
      >;
      expect(auth.clientId).toBe('test-client-id');
      expect(auth.clientSecret.value).toBe('env-client-secret');
      expect(tenant.unique.serviceAuthMode).toBe('cluster_local');
      const uniqueResult = tenant.unique;
      const unique = uniqueResult as Extract<
        typeof uniqueResult,
        { serviceAuthMode: 'cluster_local' }
      >;
      expect(unique.serviceExtraHeaders['x-company-id']).toBe('test-company');
      expect(unique.serviceExtraHeaders['x-user-id']).toBe('test-user');
      expect(tenant.processing.concurrency).toBe(1);
    });

    it('loads data-center config with pat auth', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';

      const dataCenterPatConfig = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: patAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, dataCenterPatConfig);

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      const tenant = assertFirstElement(result);
      expect(tenant.confluence.instanceType).toBe('data-center');
      expect(tenant.confluence.baseUrl).toBe('https://confluence.acme.com');
      expect(tenant.confluence.auth.mode).toBe(AuthMode.PAT);
      const auth = tenant.confluence.auth as Extract<
        typeof tenant.confluence.auth,
        { mode: typeof AuthMode.PAT }
      >;
      expect(auth.token.value).toBe('env-pat-token');
    });

    it('loads data-center config with oauth_2lo auth', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';

      const dataCenterConfig = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, dataCenterConfig);

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      const tenant = assertFirstElement(result);
      expect(tenant.confluence.instanceType).toBe('data-center');
      expect(tenant.confluence.baseUrl).toBe('https://confluence.acme.com');
      expect(tenant.confluence.auth.mode).toBe(AuthMode.OAUTH_2LO);
      const auth = tenant.confluence.auth as Extract<
        typeof tenant.confluence.auth,
        { mode: typeof AuthMode.OAUTH_2LO }
      >;
      expect(auth.clientSecret.value).toBe('env-client-secret');
    });

    it('loads multiple tenant config files', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';

      const tenant1Config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://tenant1.atlassian.net/wiki',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const tenant2Config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.tenant2.com',
          auth: { mode: AuthMode.OAUTH_2LO, clientId: 'tenant2-client-id' },
          ...baseConfluenceFields,
        },
        unique: {
          ...clusterLocalUniqueConfig,
          serviceExtraHeaders: {
            'x-company-id': 'tenant2-company',
            'x-user-id': 'tenant2-user',
          },
        },
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupFsMocks(globSync, readFileSync, [
        { path: CONFIG_PATH, config: tenant1Config },
        { path: CONFIG_PATH_2, config: tenant2Config },
      ]);

      const result = getTenantConfigs();

      expect(result).toHaveLength(2);
      const [tenant1, tenant2] = result;
      expect(tenant1?.confluence.instanceType).toBe('cloud');
      expect(tenant1?.confluence.baseUrl).toBe('https://tenant1.atlassian.net/wiki');
      expect(tenant2?.confluence.instanceType).toBe('data-center');
      expect(tenant2?.confluence.baseUrl).toBe('https://confluence.tenant2.com');
      const tenant2Auth = tenant2?.confluence.auth as Extract<
        NonNullable<typeof tenant2>['confluence']['auth'],
        { mode: typeof AuthMode.OAUTH_2LO }
      >;
      expect(tenant2Auth.clientId).toBe('tenant2-client-id');
    });
  });

  describe('secret injection', () => {
    it('injects CONFLUENCE_CLIENT_SECRET for oauth_2lo mode', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';

      const config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      const result = getTenantConfigs();

      const tenant = assertFirstElement(result);
      const auth = tenant.confluence.auth as Extract<
        typeof tenant.confluence.auth,
        { mode: typeof AuthMode.OAUTH_2LO }
      >;
      expect(auth.clientSecret.value).toBe('env-client-secret');
    });

    it('injects CONFLUENCE_PAT for pat mode', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';

      const config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: patAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      const result = getTenantConfigs();

      const tenant = assertFirstElement(result);
      const auth = tenant.confluence.auth as Extract<
        typeof tenant.confluence.auth,
        { mode: typeof AuthMode.PAT }
      >;
      expect(auth.token.value).toBe('env-pat-token');
    });

    it('does not inject CONFLUENCE_PAT when auth mode is oauth_2lo', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      process.env.CONFLUENCE_PAT = 'should-not-be-injected';

      const config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      const result = getTenantConfigs();

      const tenant = assertFirstElement(result);
      expect(tenant.confluence.auth.mode).toBe(AuthMode.OAUTH_2LO);
      expect(tenant.confluence.auth).not.toHaveProperty('token');
    });

    it('does not inject CONFLUENCE_CLIENT_SECRET when auth mode is pat', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';
      process.env.CONFLUENCE_CLIENT_SECRET = 'should-not-be-injected';

      const config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: patAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      const result = getTenantConfigs();

      const tenant = assertFirstElement(result);
      expect(tenant.confluence.auth.mode).toBe(AuthMode.PAT);
      expect(tenant.confluence.auth).not.toHaveProperty('clientSecret');
    });

    it('injects ZITADEL_CLIENT_SECRET when serviceAuthMode is external', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      process.env.ZITADEL_CLIENT_SECRET = 'env-zitadel-secret';

      const config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: externalUniqueConfigWithoutSecret,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      const result = getTenantConfigs();

      const tenant = assertFirstElement(result);
      expect(tenant.unique.serviceAuthMode).toBe('external');
      const uniqueResult = tenant.unique;
      const unique = uniqueResult as Extract<typeof uniqueResult, { serviceAuthMode: 'external' }>;
      expect(unique.zitadelClientSecret.value).toBe('env-zitadel-secret');
    });

    it('does not inject ZITADEL_CLIENT_SECRET when serviceAuthMode is cluster_local', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      process.env.ZITADEL_CLIENT_SECRET = 'should-not-be-injected';

      const config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      const result = getTenantConfigs();

      const tenant = assertFirstElement(result);
      expect(tenant.unique.serviceAuthMode).toBe('cluster_local');
      expect(tenant.unique).not.toHaveProperty('zitadelClientSecret');
    });
  });

  describe('error handling', () => {
    it('throws when TENANT_CONFIG_PATH_PATTERN is not set', async () => {
      delete process.env.TENANT_CONFIG_PATH_PATTERN;
      const { getTenantConfigs } = await loadModule();

      expect(() => getTenantConfigs()).toThrow(
        'TENANT_CONFIG_PATH_PATTERN environment variable is not set',
      );
    });

    it('throws when no config files match the pattern', async () => {
      const { globSync, getTenantConfigs } = await loadModule();
      globSync.mockReturnValue([]);

      expect(() => getTenantConfigs()).toThrow(
        "No tenant configuration files found matching pattern '/config/*.yaml'",
      );
    });

    it('throws on invalid YAML content', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      globSync.mockReturnValue([CONFIG_PATH]);
      readFileSync.mockReturnValue('key: [unterminated');

      expect(() => getTenantConfigs()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws on schema validation failure for missing required fields', async () => {
      const incompleteConfig = {
        confluence: { instanceType: 'cloud' },
        unique: {},
        processing: {},
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, incompleteConfig);

      expect(() => getTenantConfigs()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when pat auth is used with cloud instance type', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';

      const config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: patAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      expect(() => getTenantConfigs()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when auth mode is unknown', async () => {
      const config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: { mode: 'unknown_mode' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      expect(() => getTenantConfigs()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when CONFLUENCE_PAT is not set for pat auth', async () => {
      const config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: patAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      expect(() => getTenantConfigs()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when CONFLUENCE_CLIENT_SECRET is not set for oauth_2lo auth', async () => {
      const config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      expect(() => getTenantConfigs()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when ZITADEL_CLIENT_SECRET is not set for external auth mode', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';

      const config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: externalUniqueConfigWithoutSecret,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      expect(() => getTenantConfigs()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });
  });

  describe('caching', () => {
    it('returns cached configs on second call without re-reading files', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';

      const config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      const firstCall = getTenantConfigs();
      const secondCall = getTenantConfigs();

      expect(firstCall).toBe(secondCall);
      expect(globSync).toHaveBeenCalledTimes(1);
      expect(readFileSync).toHaveBeenCalledTimes(1);
    });
  });
});
