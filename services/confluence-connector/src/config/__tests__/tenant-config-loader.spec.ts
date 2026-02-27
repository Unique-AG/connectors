import assert from 'node:assert';
import { dump } from 'js-yaml';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthMode } from '../confluence.schema';

vi.mock('node:fs', () => ({
  globSync: vi.fn(),
  readFileSync: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const original = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...original,
    Logger: class MockLogger {
      public log = vi.fn();
      public warn = vi.fn();
      public error = vi.fn();
    },
  };
});

const baseProcessingConfig = {
  stepTimeoutSeconds: 300,
  concurrency: 1,
  scanIntervalCron: '*/15 * * * *',
};

const baseIngestionConfig = {
  ingestionMode: 'flat',
  scopeId: 'test-scope-id',
  ingestFiles: 'disabled',
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

const externalUniqueConfig = {
  serviceAuthMode: 'external',
  zitadelOauthTokenUrl: 'https://idp.unique.app/oauth/v2/token',
  zitadelProjectId: 'test-project-id',
  zitadelClientId: 'test-client-id',
  zitadelClientSecret: 'os.environ/ZITADEL_CLIENT_SECRET',
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
  clientSecret: 'os.environ/CONFLUENCE_CLIENT_SECRET',
};

const patAuth = {
  mode: AuthMode.PAT,
  token: 'os.environ/CONFLUENCE_PAT',
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
  ] as const;

  const envBackup: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of envKeysToClean) {
      envBackup[key] = process.env[key];
    }
    process.env.TENANT_CONFIG_PATH_PATTERN = '/config/*-tenant-config.yaml';
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
    const mod = await import('../tenant-config-loader');
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
    path = '/config/acme-tenant-config.yaml',
  ) {
    setupFsMocks(globSync, readFileSync, [{ path, config }]);
  }

  function makeCloudOauth2loConfig(overrides?: Record<string, unknown>) {
    return {
      confluence: {
        instanceType: 'cloud',
        cloudId: 'test-cloud-id',
        baseUrl: 'https://acme.atlassian.net',
        auth: oauth2loAuth,
        ...baseConfluenceFields,
      },
      unique: clusterLocalUniqueConfig,
      processing: baseProcessingConfig,
      ingestion: baseIngestionConfig,
      ...overrides,
    };
  }

  function makeDataCenterPatConfig(overrides?: Record<string, unknown>) {
    return {
      confluence: {
        instanceType: 'data-center',
        baseUrl: 'https://confluence.acme.com',
        auth: patAuth,
        ...baseConfluenceFields,
      },
      unique: clusterLocalUniqueConfig,
      processing: baseProcessingConfig,
      ingestion: baseIngestionConfig,
      ...overrides,
    };
  }

  describe('tenant name extraction', () => {
    it('extracts tenant name from filename', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(
        globSync,
        readFileSync,
        makeCloudOauth2loConfig(),
        '/config/acme-tenant-config.yaml',
      );

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      expect(assertFirstElement(result).name).toBe('acme');
    });

    it('extracts multi-segment tenant name from filename', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(
        globSync,
        readFileSync,
        makeCloudOauth2loConfig(),
        '/config/acme-corp-tenant-config.yaml',
      );

      const result = getTenantConfigs();

      expect(assertFirstElement(result).name).toBe('acme-corp');
    });

    it('extracts "default" from default-tenant-config.yaml', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(
        globSync,
        readFileSync,
        makeCloudOauth2loConfig(),
        '/config/default-tenant-config.yaml',
      );

      const result = getTenantConfigs();

      expect(assertFirstElement(result).name).toBe('default');
    });
  });

  describe('tenant name validation', () => {
    it('rejects tenant names with uppercase characters', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(
        globSync,
        readFileSync,
        makeCloudOauth2loConfig(),
        '/config/Acme-tenant-config.yaml',
      );

      expect(() => getTenantConfigs()).toThrow(/Invalid tenant name 'Acme'/);
    });

    it('rejects tenant names with underscores', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(
        globSync,
        readFileSync,
        makeCloudOauth2loConfig(),
        '/config/acme_corp-tenant-config.yaml',
      );

      expect(() => getTenantConfigs()).toThrow(/Invalid tenant name 'acme_corp'/);
    });

    it('rejects tenant names with trailing dash', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(
        globSync,
        readFileSync,
        makeCloudOauth2loConfig(),
        '/config/acme--tenant-config.yaml',
      );

      expect(() => getTenantConfigs()).toThrow(/Invalid tenant name 'acme-'/);
    });

    it('rejects duplicate tenant names', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupFsMocks(globSync, readFileSync, [
        { path: '/config/a/acme-tenant-config.yaml', config: makeCloudOauth2loConfig() },
        { path: '/config/b/acme-tenant-config.yaml', config: makeCloudOauth2loConfig() },
      ]);

      expect(() => getTenantConfigs()).toThrow(/Duplicate tenant name 'acme'/);
    });
  });

  describe('tenant status', () => {
    it('includes active tenants in results', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeCloudOauth2loConfig({ status: 'active' }));

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      expect(assertFirstElement(result).name).toBe('acme');
    });

    it('defaults to active when status is omitted', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeCloudOauth2loConfig());

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
    });

    it('excludes inactive tenants from results but validates config', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupFsMocks(globSync, readFileSync, [
        {
          path: '/config/alpha-tenant-config.yaml',
          config: makeCloudOauth2loConfig({ status: 'active' }),
        },
        {
          path: '/config/beta-tenant-config.yaml',
          config: makeCloudOauth2loConfig({ status: 'inactive' }),
        },
      ]);

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      expect(assertFirstElement(result).name).toBe('alpha');
    });

    it('fails validation for inactive tenant with invalid config', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      const invalidConfig = {
        status: 'inactive',
        confluence: { instanceType: 'cloud' },
        unique: {},
        processing: {},
      };
      setupSingleConfig(globSync, readFileSync, invalidConfig);

      expect(() => getTenantConfigs()).toThrow(/Failed to load or validate tenant config/);
    });

    it('excludes deleted tenants without validating config', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      const deletedConfig = { status: 'deleted', confluence: 'totally-invalid' };
      setupFsMocks(globSync, readFileSync, [
        { path: '/config/active-tenant-config.yaml', config: makeCloudOauth2loConfig() },
        { path: '/config/removed-tenant-config.yaml', config: deletedConfig },
      ]);

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      expect(assertFirstElement(result).name).toBe('active');
    });

    it('throws when all tenants are inactive or deleted', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupFsMocks(globSync, readFileSync, [
        {
          path: '/config/alpha-tenant-config.yaml',
          config: makeCloudOauth2loConfig({ status: 'inactive' }),
        },
        { path: '/config/beta-tenant-config.yaml', config: { status: 'deleted' } },
      ]);

      expect(() => getTenantConfigs()).toThrow(
        'No active tenant configurations found. At least one tenant must have status "active".',
      );
    });
  });

  describe('valid config loading', () => {
    it('loads cloud config with oauth_2lo auth', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeCloudOauth2loConfig());

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      const { name, config } = assertFirstElement(result);
      expect(name).toBe('acme');
      expect(config.confluence.instanceType).toBe('cloud');
      expect(config.confluence.baseUrl).toBe('https://acme.atlassian.net');
      expect(config.confluence.auth.mode).toBe(AuthMode.OAUTH_2LO);
      const auth = config.confluence.auth as Extract<
        typeof config.confluence.auth,
        { mode: typeof AuthMode.OAUTH_2LO }
      >;
      expect(auth.clientId).toBe('test-client-id');
      expect(auth.clientSecret.value).toBe('env-client-secret');
      expect(config.unique.serviceAuthMode).toBe('cluster_local');
      expect(config.processing.concurrency).toBe(1);
    });

    it('loads data-center config with pat auth', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeDataCenterPatConfig());

      const result = getTenantConfigs();

      expect(result).toHaveLength(1);
      const { config } = assertFirstElement(result);
      expect(config.confluence.instanceType).toBe('data-center');
      expect(config.confluence.auth.mode).toBe(AuthMode.PAT);
      const auth = config.confluence.auth as Extract<
        typeof config.confluence.auth,
        { mode: typeof AuthMode.PAT }
      >;
      expect(auth.token.value).toBe('env-pat-token');
    });

    it('loads multiple active tenants with different auth modes', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      process.env.CONFLUENCE_PAT = 'env-pat-token';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();

      const tenant1Config = {
        confluence: {
          instanceType: 'cloud',
          cloudId: 'tenant1-cloud-id',
          baseUrl: 'https://tenant1.atlassian.net',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
        ingestion: baseIngestionConfig,
      };

      const tenant2Config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.tenant2.com',
          auth: patAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
        ingestion: baseIngestionConfig,
      };

      setupFsMocks(globSync, readFileSync, [
        { path: '/config/tenant1-tenant-config.yaml', config: tenant1Config },
        { path: '/config/tenant2-tenant-config.yaml', config: tenant2Config },
      ]);

      const result = getTenantConfigs();

      expect(result).toHaveLength(2);
      expect(result[0]?.name).toBe('tenant1');
      expect(result[0]?.config.confluence.auth.mode).toBe(AuthMode.OAUTH_2LO);
      expect(result[1]?.name).toBe('tenant2');
      expect(result[1]?.config.confluence.auth.mode).toBe(AuthMode.PAT);
    });
  });

  describe('os.environ/ secret resolution', () => {
    it('resolves CONFLUENCE_CLIENT_SECRET via os.environ/ reference', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeCloudOauth2loConfig());

      const { config } = assertFirstElement(getTenantConfigs());
      const auth = config.confluence.auth as Extract<
        typeof config.confluence.auth,
        { mode: typeof AuthMode.OAUTH_2LO }
      >;
      expect(auth.clientSecret.value).toBe('env-client-secret');
    });

    it('resolves CONFLUENCE_PAT via os.environ/ reference', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeDataCenterPatConfig());

      const { config } = assertFirstElement(getTenantConfigs());
      const auth = config.confluence.auth as Extract<
        typeof config.confluence.auth,
        { mode: typeof AuthMode.PAT }
      >;
      expect(auth.token.value).toBe('env-pat-token');
    });

    it('resolves ZITADEL_CLIENT_SECRET via os.environ/ reference', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      process.env.ZITADEL_CLIENT_SECRET = 'env-zitadel-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();

      const config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: externalUniqueConfig,
        processing: baseProcessingConfig,
        ingestion: baseIngestionConfig,
      };
      setupSingleConfig(globSync, readFileSync, config);

      const { config: tenantConfig } = assertFirstElement(getTenantConfigs());
      expect(tenantConfig.unique.serviceAuthMode).toBe('external');
      const unique = tenantConfig.unique as Extract<
        typeof tenantConfig.unique,
        { serviceAuthMode: 'external' }
      >;
      expect(unique.zitadelClientSecret.value).toBe('env-zitadel-secret');
    });

    it('fails validation when CONFLUENCE_CLIENT_SECRET env var is not set', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeCloudOauth2loConfig());

      expect(() => getTenantConfigs()).toThrow(/Failed to load or validate tenant config/);
    });

    it('fails validation when CONFLUENCE_PAT env var is not set', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeDataCenterPatConfig());

      expect(() => getTenantConfigs()).toThrow(/Failed to load or validate tenant config/);
    });

    it('fails validation when ZITADEL_CLIENT_SECRET env var is not set', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();

      const config = {
        confluence: {
          instanceType: 'data-center',
          baseUrl: 'https://confluence.acme.com',
          auth: oauth2loAuth,
          ...baseConfluenceFields,
        },
        unique: externalUniqueConfig,
        processing: baseProcessingConfig,
        ingestion: baseIngestionConfig,
      };
      setupSingleConfig(globSync, readFileSync, config);

      expect(() => getTenantConfigs()).toThrow(/Failed to load or validate tenant config/);
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
        "No tenant configuration files found matching pattern '/config/*-tenant-config.yaml'",
      );
    });

    it('throws on invalid YAML content', async () => {
      const configPath = '/config/acme-tenant-config.yaml';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      globSync.mockReturnValue([configPath]);
      readFileSync.mockReturnValue('key: [unterminated');

      expect(() => getTenantConfigs()).toThrow(
        `Failed to load or validate tenant config from ${configPath}`,
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

      expect(() => getTenantConfigs()).toThrow(/Failed to load or validate tenant config/);
    });

    it('throws when pat auth is used with cloud instance type', async () => {
      process.env.CONFLUENCE_PAT = 'env-pat-token';
      const config = {
        confluence: {
          instanceType: 'cloud',
          cloudId: 'test-cloud-id',
          baseUrl: 'https://acme.atlassian.net',
          auth: patAuth,
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
        ingestion: baseIngestionConfig,
      };
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      expect(() => getTenantConfigs()).toThrow(/Failed to load or validate tenant config/);
    });

    it('throws when auth mode is unknown', async () => {
      const config = {
        confluence: {
          instanceType: 'cloud',
          cloudId: 'test-cloud-id',
          baseUrl: 'https://acme.atlassian.net',
          auth: { mode: 'unknown_mode' },
          ...baseConfluenceFields,
        },
        unique: clusterLocalUniqueConfig,
        processing: baseProcessingConfig,
        ingestion: baseIngestionConfig,
      };
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, config);

      expect(() => getTenantConfigs()).toThrow(/Failed to load or validate tenant config/);
    });

    it('throws when ingestionMode is recursive', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(
        globSync,
        readFileSync,
        makeCloudOauth2loConfig({
          ingestion: { ...baseIngestionConfig, ingestionMode: 'recursive' },
        }),
      );

      expect(() => getTenantConfigs()).toThrow(/Failed to load or validate tenant config/);
    });

    it('throws when filename does not have tenant-config suffix', async () => {
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      globSync.mockReturnValue(['/config/acme.yaml']);
      readFileSync.mockReturnValue(dump(makeCloudOauth2loConfig()));

      expect(() => getTenantConfigs()).toThrow(/does not end with '-tenant-config\.yaml'/);
    });
  });

  describe('caching', () => {
    it('returns cached configs on second call without re-reading files', async () => {
      process.env.CONFLUENCE_CLIENT_SECRET = 'env-client-secret';
      const { globSync, readFileSync, getTenantConfigs } = await loadModule();
      setupSingleConfig(globSync, readFileSync, makeCloudOauth2loConfig());

      const firstCall = getTenantConfigs();
      const secondCall = getTenantConfigs();

      expect(firstCall).toBe(secondCall);
      expect(globSync).toHaveBeenCalledTimes(1);
      expect(readFileSync).toHaveBeenCalledTimes(1);
    });
  });
});
