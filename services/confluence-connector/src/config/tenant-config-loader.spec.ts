import { dump } from 'js-yaml';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('node:fs', () => ({
  globSync: vi.fn(),
  readFileSync: vi.fn(),
}));

const CONFIG_PATH = '/config/tenant.yaml';

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

describe('tenant-config-loader', () => {
  const envKeysToClean = [
    'TENANT_CONFIG_PATH_PATTERN',
    'CONFLUENCE_API_TOKEN',
    'CONFLUENCE_PAT',
    'CONFLUENCE_PASSWORD',
    'ZITADEL_CLIENT_SECRET',
  ] as const;

  const envBackup: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of envKeysToClean) {
      envBackup[key] = process.env[key];
    }
    process.env.TENANT_CONFIG_PATH_PATTERN = '/config/*.yaml';
    delete process.env.CONFLUENCE_API_TOKEN;
    delete process.env.CONFLUENCE_PAT;
    delete process.env.CONFLUENCE_PASSWORD;
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
    config: Record<string, unknown>,
  ) {
    globSync.mockReturnValue([CONFIG_PATH]);
    readFileSync.mockReturnValue(dump(config));
  }

  describe('valid config loading', () => {
    it('loads cloud config with api_token auth injected from environment', async () => {
      process.env.CONFLUENCE_API_TOKEN = 'env-api-token';

      const cloudConfig = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: { mode: 'api_token', email: 'user@acme.com' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, cloudConfig);

      const result = getTenantConfig();

      expect(result.confluence.instanceType).toBe('cloud');
      expect(result.confluence.baseUrl).toBe('https://acme.atlassian.net/wiki');
      expect(result.confluence.auth.mode).toBe('api_token');
      const auth = result.confluence.auth as Extract<
        typeof result.confluence.auth,
        { mode: 'api_token' }
      >;
      expect(auth.email).toBe('user@acme.com');
      expect(auth.apiToken.value).toBe('env-api-token');
      expect(result.unique.serviceAuthMode).toBe('cluster_local');
      expect(result.processing.concurrency).toBe(1);
    });

    it('loads onprem config with PAT auth injected from environment', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';

      const patConfig = {
        confluence: {
          instanceType: 'onprem',
          baseUrl: 'https://confluence.acme.com',
          auth: { mode: 'pat' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, patConfig);

      const result = getTenantConfig();

      expect(result.confluence.instanceType).toBe('onprem');
      expect(result.confluence.auth.mode).toBe('pat');
      const auth = result.confluence.auth as Extract<
        typeof result.confluence.auth,
        { mode: 'pat' }
      >;
      expect(auth.token.value).toBe('env-pat-token');
    });

    it('loads onprem config with basic auth password injected from environment', async () => {
      process.env.CONFLUENCE_PASSWORD = 'env-password';

      const basicConfig = {
        confluence: {
          instanceType: 'onprem',
          baseUrl: 'https://confluence.acme.com',
          auth: { mode: 'basic', username: 'admin' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, basicConfig);

      const result = getTenantConfig();

      expect(result.confluence.auth.mode).toBe('basic');
      const auth = result.confluence.auth as Extract<
        typeof result.confluence.auth,
        { mode: 'basic' }
      >;
      expect(auth.username).toBe('admin');
      expect(auth.password.value).toBe('env-password');
    });
  });

  describe('secret injection', () => {
    it('injects ZITADEL_CLIENT_SECRET when serviceAuthMode is external', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';
      process.env.ZITADEL_CLIENT_SECRET = 'env-zitadel-secret';

      const externalConfig = {
        confluence: {
          instanceType: 'onprem',
          baseUrl: 'https://confluence.acme.com',
          auth: { mode: 'pat' },
          ...baseConfluenceFields,
        },
        unique: externalUniqueConfigWithoutSecret,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, externalConfig);

      const result = getTenantConfig();

      expect(result.unique.serviceAuthMode).toBe('external');
      const unique = result.unique as Extract<
        typeof result.unique,
        { serviceAuthMode: 'external' }
      >;
      expect(unique.zitadelClientSecret.value).toBe('env-zitadel-secret');
    });

    it('does not inject ZITADEL_CLIENT_SECRET when serviceAuthMode is cluster_local', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';
      process.env.ZITADEL_CLIENT_SECRET = 'should-not-be-injected';

      const config = {
        confluence: {
          instanceType: 'onprem',
          baseUrl: 'https://confluence.acme.com',
          auth: { mode: 'pat' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, config);

      const result = getTenantConfig();

      expect(result.unique.serviceAuthMode).toBe('cluster_local');
      expect(result.unique).not.toHaveProperty('zitadelClientSecret');
    });
  });

  describe('error handling', () => {
    it('throws when TENANT_CONFIG_PATH_PATTERN is not set', async () => {
      delete process.env.TENANT_CONFIG_PATH_PATTERN;
      const { getTenantConfig } = await loadModule();

      expect(() => getTenantConfig()).toThrow(
        'TENANT_CONFIG_PATH_PATTERN environment variable is not set',
      );
    });

    it('throws when no config files match the pattern', async () => {
      const { globSync, getTenantConfig } = await loadModule();
      globSync.mockReturnValue([]);

      expect(() => getTenantConfig()).toThrow(
        "No tenant configuration files found matching pattern '/config/*.yaml'",
      );
    });

    it('throws when multiple config files are found', async () => {
      const { globSync, getTenantConfig } = await loadModule();
      globSync.mockReturnValue(['/config/a.yaml', '/config/b.yaml']);

      expect(() => getTenantConfig()).toThrow(
        'Multiple tenant configuration files found matching pattern',
      );
    });

    it('throws on invalid YAML content', async () => {
      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      globSync.mockReturnValue([CONFIG_PATH]);
      readFileSync.mockReturnValue('key: [unterminated');

      expect(() => getTenantConfig()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws on schema validation failure for missing required fields', async () => {
      const incompleteConfig = {
        confluence: { instanceType: 'cloud' },
        unique: {},
        processing: {},
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, incompleteConfig);

      expect(() => getTenantConfig()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when CONFLUENCE_API_TOKEN is not set for api_token auth mode', async () => {
      const config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: { mode: 'api_token', email: 'user@acme.com' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, config);

      expect(() => getTenantConfig()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when CONFLUENCE_PAT is not set for pat auth mode', async () => {
      const config = {
        confluence: {
          instanceType: 'onprem',
          baseUrl: 'https://confluence.acme.com',
          auth: { mode: 'pat' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, config);

      expect(() => getTenantConfig()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when CONFLUENCE_PASSWORD is not set for basic auth mode', async () => {
      const config = {
        confluence: {
          instanceType: 'onprem',
          baseUrl: 'https://confluence.acme.com',
          auth: { mode: 'basic', username: 'admin' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, config);

      expect(() => getTenantConfig()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });

    it('throws when ZITADEL_CLIENT_SECRET is not set for external auth mode', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';

      const config = {
        confluence: {
          instanceType: 'onprem',
          baseUrl: 'https://confluence.acme.com',
          auth: { mode: 'pat' },
          ...baseConfluenceFields,
        },
        unique: externalUniqueConfigWithoutSecret,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, config);

      expect(() => getTenantConfig()).toThrow(
        `Failed to load or validate tenant config from ${CONFIG_PATH}`,
      );
    });
  });

  describe('caching', () => {
    it('returns cached config on second call without re-reading the file', async () => {
      process.env.CONFLUENCE_API_TOKEN = 'env-api-token';

      const config = {
        confluence: {
          instanceType: 'cloud',
          baseUrl: 'https://acme.atlassian.net/wiki',
          auth: { mode: 'api_token', email: 'user@acme.com' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
      };

      const { globSync, readFileSync, getTenantConfig } = await loadModule();
      setupFsMocks(globSync, readFileSync, config);

      const first = getTenantConfig();
      const second = getTenantConfig();

      expect(first).toBe(second);
      expect(globSync).toHaveBeenCalledTimes(1);
      expect(readFileSync).toHaveBeenCalledTimes(1);
    });
  });
});
