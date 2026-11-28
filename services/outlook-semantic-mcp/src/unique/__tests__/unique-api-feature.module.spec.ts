import { afterEach, describe, expect, it, vi } from 'vitest';

const UNIQUE_OFF_ENV = {
  MCP_BACKEND: 'microsoft_graph',
  UNIQUE_ATTACHMENTS: 'disabled',
  UNIQUE_SERVICE_AUTH_MODE: undefined,
  UNIQUE_SERVICE_EXTRA_HEADERS: undefined,
  UNIQUE_INGESTION_SERVICE_BASE_URL: undefined,
  UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL: undefined,
};

describe('UniqueApiFeatureModule', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('provides a client that refuses every call when no enabled feature needs Unique', async () => {
    for (const [key, value] of Object.entries(UNIQUE_OFF_ENV)) {
      vi.stubEnv(key, value);
    }
    vi.resetModules();
    // Imported after the env is set: the module picks the client when its file loads.
    const { Test } = await import('@nestjs/testing');
    const { getUniqueApiClientToken } = await import('@unique-ag/unique-api');
    const { UploadFileForIngestionCommand } = await import('../upload-file-for-ingestion.command');
    const { UnavailableUniqueApiClient, UniqueApiFeatureModule } = await import(
      '../unique-api.module'
    );

    const moduleRef = await Test.createTestingModule({ imports: [UniqueApiFeatureModule] })
      .overrideProvider(UploadFileForIngestionCommand)
      .useValue({})
      .compile();
    const client = moduleRef.get(getUniqueApiClientToken('outlook-semantic-mcp'));

    expect(client).toBeInstanceOf(UnavailableUniqueApiClient);
    expect(() => client.scopes).toThrow(
      'The Unique API client was used (scopes) although no enabled feature needs Unique.',
    );
    expect(() => client.content).toThrow(/\(content\)/);
    await moduleRef.close();
  });
});
