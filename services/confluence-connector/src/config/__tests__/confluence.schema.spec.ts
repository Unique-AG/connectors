import { describe, expect, it } from 'vitest';
import { ConfluenceConfigSchema } from '../confluence.schema';

const baseCloudInput = {
  instanceType: 'cloud',
  cloudId: 'my-cloud-id',
  baseUrl: 'https://mysite.atlassian.net',
  apiRateLimitPerMinute: 120,
  ingestSingleLabel: 'ai-ingest',
  ingestAllLabel: 'ai-ingest-all',
  auth: {
    mode: 'oauth_2lo',
    clientId: 'client-id',
    clientSecret: 'client-secret',
  },
} as const;

const baseDataCenterInput = {
  instanceType: 'data-center',
  baseUrl: 'https://confluence.company.com',
  apiRateLimitPerMinute: 60,
  ingestSingleLabel: 'ai-ingest',
  ingestAllLabel: 'ai-ingest-all',
} as const;

describe('ConfluenceConfigSchema', () => {
  describe('cloud instance', () => {
    it('parses a valid cloud configuration', () => {
      const result = ConfluenceConfigSchema.parse(baseCloudInput);

      expect(result.instanceType).toBe('cloud');
      expect(result.baseUrl).toBe('https://mysite.atlassian.net');
      expect(result.apiRateLimitPerMinute).toBe(120);
      if (result.instanceType === 'cloud') {
        expect(result.cloudId).toBe('my-cloud-id');
      }
    });

    it('wraps clientSecret in Redacted', () => {
      const result = ConfluenceConfigSchema.parse(baseCloudInput);

      expect(result.auth.mode).toBe('oauth_2lo');
      if (result.auth.mode === 'oauth_2lo') {
        expect(result.auth.clientSecret.value).toBe('client-secret');
        expect(String(result.auth.clientSecret)).toBe('[Redacted]');
      }
    });

    it('coerces string apiRateLimitPerMinute to a number', () => {
      const result = ConfluenceConfigSchema.parse({
        ...baseCloudInput,
        apiRateLimitPerMinute: '200',
      });

      expect(result.apiRateLimitPerMinute).toBe(200);
    });

    it('rejects a URL with a trailing slash', () => {
      expect(() =>
        ConfluenceConfigSchema.parse({
          ...baseCloudInput,
          baseUrl: 'https://mysite.atlassian.net/',
        }),
      ).toThrow();
    });

    it('rejects an invalid URL', () => {
      expect(() =>
        ConfluenceConfigSchema.parse({ ...baseCloudInput, baseUrl: 'not-a-url' }),
      ).toThrow();
    });

    it('rejects when cloudId is missing', () => {
      const { cloudId: _, ...withoutCloudId } = baseCloudInput;
      expect(() => ConfluenceConfigSchema.parse(withoutCloudId)).toThrow();
    });

    it('rejects non-oauth_2lo auth for cloud instance type', () => {
      expect(() =>
        ConfluenceConfigSchema.parse({
          ...baseCloudInput,
          auth: { mode: 'pat', token: 'my-token' },
        }),
      ).toThrow();
    });
  });

  describe('data-center instance with oauth_2lo auth', () => {
    it('parses a valid data-center oauth_2lo configuration', () => {
      const result = ConfluenceConfigSchema.parse({
        ...baseDataCenterInput,
        auth: { mode: 'oauth_2lo', clientId: 'dc-client', clientSecret: 'dc-secret' },
      });

      expect(result.instanceType).toBe('data-center');
      expect(result.auth.mode).toBe('oauth_2lo');
    });
  });

  describe('data-center instance with pat auth', () => {
    it('parses a valid data-center PAT configuration', () => {
      const result = ConfluenceConfigSchema.parse({
        ...baseDataCenterInput,
        auth: { mode: 'pat', token: 'my-personal-token' },
      });

      expect(result.instanceType).toBe('data-center');
      expect(result.auth.mode).toBe('pat');
      if (result.auth.mode === 'pat') {
        expect(result.auth.token.value).toBe('my-personal-token');
      }
    });

    it('wraps PAT token in Redacted', () => {
      const result = ConfluenceConfigSchema.parse({
        ...baseDataCenterInput,
        auth: { mode: 'pat', token: 'secret-token' },
      });

      if (result.auth.mode === 'pat') {
        expect(String(result.auth.token)).toBe('[Redacted]');
      }
    });
  });

  describe('env reference resolution', () => {
    it('resolves os.environ/ prefix to the actual env variable', () => {
      process.env.TEST_CONFLUENCE_SECRET = 'resolved-secret';

      const result = ConfluenceConfigSchema.parse({
        ...baseCloudInput,
        auth: { ...baseCloudInput.auth, clientSecret: 'os.environ/TEST_CONFLUENCE_SECRET' },
      });

      if (result.auth.mode === 'oauth_2lo') {
        expect(result.auth.clientSecret.value).toBe('resolved-secret');
      }

      delete process.env.TEST_CONFLUENCE_SECRET;
    });
  });
});
