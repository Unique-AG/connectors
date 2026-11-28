import { afterEach, describe, expect, it, vi } from 'vitest';
import { uniqueConfig } from '../unique.config';

const UNIQUE_ENV = {
  UNIQUE_SERVICE_AUTH_MODE: 'cluster_local',
  UNIQUE_SERVICE_EXTRA_HEADERS: '{"x-company-id":"company-1","x-user-id":"user-1"}',
  UNIQUE_INGESTION_SERVICE_BASE_URL: 'http://ingestion:8091',
  UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL: 'http://scope-management:8094',
};

const loadWith = (env: Record<string, string | undefined>) => {
  const ambientUniqueKeys = Object.keys(process.env).filter((key) => key.startsWith('UNIQUE_'));
  for (const key of [...ambientUniqueKeys, 'MCP_BACKEND']) {
    vi.stubEnv(key, undefined);
  }
  for (const [key, value] of Object.entries(env)) {
    vi.stubEnv(key, value);
  }
  return uniqueConfig();
};

describe('uniqueConfig', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('is disabled without any UNIQUE_* variable in microsoft_graph mode with Unique attachments off', async () => {
    await expect(
      loadWith({ MCP_BACKEND: 'microsoft_graph', UNIQUE_ATTACHMENTS: 'disabled' }),
    ).resolves.toEqual({ enabled: false });
  });

  it('ignores a partial Unique config when Unique is off', async () => {
    await expect(
      loadWith({
        MCP_BACKEND: 'microsoft_graph',
        UNIQUE_ATTACHMENTS: 'disabled',
        UNIQUE_SERVICE_AUTH_MODE: 'external',
      }),
    ).resolves.toEqual({ enabled: false });
  });

  it('reads the connection in Unique mode', async () => {
    await expect(
      loadWith({ MCP_BACKEND: 'microsoft_graph_and_unique_api', ...UNIQUE_ENV }),
    ).resolves.toEqual({
      enabled: true,
      serviceAuthMode: 'cluster_local',
      serviceExtraHeaders: { 'x-company-id': 'company-1', 'x-user-id': 'user-1' },
      ingestionServiceBaseUrl: 'http://ingestion:8091',
      scopeManagementServiceBaseUrl: 'http://scope-management:8094',
      storeInternally: true,
    });
  });

  it('throws naming each missing variable in Unique mode', async () => {
    const load = loadWith({
      MCP_BACKEND: 'microsoft_graph_and_unique_api',
      UNIQUE_ATTACHMENTS: 'disabled',
    });

    await expect(load).rejects.toThrow(/UNIQUE_SERVICE_AUTH_MODE: /);
    await expect(load).rejects.toThrow(/UNIQUE_INGESTION_SERVICE_BASE_URL: /);
    await expect(load).rejects.toThrow(/UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL: /);
  });

  it('throws naming the missing Zitadel secret in external auth mode', async () => {
    await expect(
      loadWith({
        MCP_BACKEND: 'microsoft_graph_and_unique_api',
        ...UNIQUE_ENV,
        UNIQUE_SERVICE_AUTH_MODE: 'external',
        UNIQUE_ZITADEL_OAUTH_TOKEN_URL: 'https://zitadel.example/oauth/v2/token',
        UNIQUE_ZITADEL_CLIENT_ID: 'client-1',
        UNIQUE_ZITADEL_PROJECT_ID: 'project-1',
      }),
    ).rejects.toThrow(/UNIQUE_ZITADEL_CLIENT_SECRET: /);
  });

  it('requires the connection in microsoft_graph mode while Unique attachments are on by default', async () => {
    await expect(loadWith({ MCP_BACKEND: 'microsoft_graph' })).rejects.toThrow(
      /UNIQUE_INGESTION_SERVICE_BASE_URL: .*UNIQUE_ATTACHMENTS=enabled/,
    );
  });
});
