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
  });

  it('rejects development authentication in production', () => {
    expect(() =>
      loadConfig({ ...requiredEnvironment, NODE_ENV: 'production', AUTH_MODE: 'development' }),
    ).toThrow(/development authentication is forbidden/);
  });

  it('rejects missing required dependencies', () => {
    expect(() => loadConfig({ ...requiredEnvironment, AMQP_URL: undefined })).toThrow(/AMQP_URL/);
  });
});
