import { describe, expect, it } from 'vitest';
import { loadConfig } from './config.js';

const requiredEnvironment = {
  DATABASE_URL: 'postgresql://localhost/a2a',
  AMQP_URL: 'amqp://localhost',
  PUBLIC_BASE_URL: 'https://a2a.example.com',
  ZITADEL_ISSUER: 'https://id.example.com',
  UNIQUE_CHAT_URL: 'http://chat',
  UNIQUE_SCOPE_MANAGEMENT_URL: 'http://scope-management',
  UNIQUE_INGESTION_URL: 'http://ingestion',
  ENCRYPTION_KEY: 'a'.repeat(64),
};

describe('loadConfig', () => {
  it('validates and applies safe defaults', () => {
    const config = loadConfig(requiredEnvironment);

    expect(config.authMode).toBe('kong');
    expect(config.workerEnabled).toBe(true);
    expect(config.databaseUrl.protocol).toBe('postgresql:');
    expect(config.corsAllowedOrigins).toEqual([]);
  });

  it('rejects development authentication in production', () => {
    expect(() =>
      loadConfig({ ...requiredEnvironment, NODE_ENV: 'production', AUTH_MODE: 'development' }),
    ).toThrow(/development authentication is forbidden/);
  });

  it.each([
    'http://id.example',
    'https://user:password@id.example',
    'https://id.example?token=secret',
  ])('rejects insecure public OAuth configuration %s', (url) => {
    expect(() =>
      loadConfig({ ...requiredEnvironment, NODE_ENV: 'production', ZITADEL_ISSUER: url }),
    ).toThrow();
  });

  it('accepts only clean CORS origins', () => {
    expect(
      loadConfig({
        ...requiredEnvironment,
        CORS_ALLOWED_ORIGINS: 'http://localhost:3006,https://admin.example.com',
      }).corsAllowedOrigins,
    ).toEqual(['http://localhost:3006', 'https://admin.example.com']);
    expect(() =>
      loadConfig({
        ...requiredEnvironment,
        CORS_ALLOWED_ORIGINS: 'https://admin.example.com/path',
      }),
    ).toThrow(/CORS origins/);
  });

  it('rejects missing required dependencies', () => {
    expect(() => loadConfig({ ...requiredEnvironment, AMQP_URL: undefined })).toThrow(/AMQP_URL/);
  });
});
