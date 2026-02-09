import { describe, expect, it } from 'vitest';
import { AppConfigSchema, ConfigEmitEvent } from './app.config';

describe('AppConfigSchema', () => {
  const validConfig = {
    tenantConfigPathPattern: '/app/tenant-configs/*-tenant-config.yaml',
  };

  describe('prefault defaults', () => {
    it('applies all defaults when only required fields are provided', () => {
      const result = AppConfigSchema.parse(validConfig);

      expect(result.nodeEnv).toBe('production');
      expect(result.port).toBe(9542);
      expect(result.logLevel).toBe('info');
      expect(result.logsDiagnosticsDataPolicy).toBe('conceal');
      expect(result.logsDiagnosticsConfigEmitPolicy).toEqual({
        emit: 'on',
        events: ['on_startup', 'per_sync'],
      });
      expect(result.isDev).toBe(false);
    });
  });

  describe('nodeEnv', () => {
    it.each(['development', 'production', 'test'] as const)('accepts "%s"', (nodeEnv) => {
      const result = AppConfigSchema.parse({ ...validConfig, nodeEnv });

      expect(result.nodeEnv).toBe(nodeEnv);
    });

    it('rejects an invalid environment', () => {
      expect(() => AppConfigSchema.parse({ ...validConfig, nodeEnv: 'staging' })).toThrow();
    });
  });

  describe('port', () => {
    it('coerces a string to a number', () => {
      const result = AppConfigSchema.parse({ ...validConfig, port: '3000' });

      expect(result.port).toBe(3000);
    });

    it('accepts port 0', () => {
      const result = AppConfigSchema.parse({ ...validConfig, port: 0 });

      expect(result.port).toBe(0);
    });

    it('accepts port 65535', () => {
      const result = AppConfigSchema.parse({ ...validConfig, port: 65535 });

      expect(result.port).toBe(65535);
    });

    it('rejects a port above 65535', () => {
      expect(() => AppConfigSchema.parse({ ...validConfig, port: 65536 })).toThrow();
    });

    it('rejects a negative port', () => {
      expect(() => AppConfigSchema.parse({ ...validConfig, port: -1 })).toThrow();
    });

    it('rejects a non-integer port', () => {
      expect(() => AppConfigSchema.parse({ ...validConfig, port: 3000.5 })).toThrow();
    });
  });

  describe('logLevel', () => {
    it.each([
      'fatal',
      'error',
      'warn',
      'info',
      'debug',
      'trace',
      'silent',
    ] as const)('accepts "%s"', (logLevel) => {
      const result = AppConfigSchema.parse({ ...validConfig, logLevel });

      expect(result.logLevel).toBe(logLevel);
    });

    it('rejects an invalid log level', () => {
      expect(() => AppConfigSchema.parse({ ...validConfig, logLevel: 'verbose' })).toThrow();
    });
  });

  describe('logsDiagnosticsDataPolicy', () => {
    it.each(['conceal', 'disclose'] as const)('accepts "%s"', (policy) => {
      const result = AppConfigSchema.parse({ ...validConfig, logsDiagnosticsDataPolicy: policy });

      expect(result.logsDiagnosticsDataPolicy).toBe(policy);
    });

    it('rejects an invalid policy', () => {
      expect(() =>
        AppConfigSchema.parse({ ...validConfig, logsDiagnosticsDataPolicy: 'redact' }),
      ).toThrow();
    });
  });

  describe('logsDiagnosticsConfigEmitPolicy', () => {
    it('parses JSON object string with both events', () => {
      const result = AppConfigSchema.parse({
        ...validConfig,
        logsDiagnosticsConfigEmitPolicy: '{"emit":"on","events":["on_startup","per_sync"]}',
      });

      expect(result.logsDiagnosticsConfigEmitPolicy).toEqual({
        emit: 'on',
        events: ['on_startup', 'per_sync'],
      });
    });

    it('parses JSON object string with single event', () => {
      const result = AppConfigSchema.parse({
        ...validConfig,
        logsDiagnosticsConfigEmitPolicy: '{"emit":"on","events":["on_startup"]}',
      });

      expect(result.logsDiagnosticsConfigEmitPolicy).toEqual({
        emit: 'on',
        events: ['on_startup'],
      });
    });

    it('parses JSON object string with emit off', () => {
      const result = AppConfigSchema.parse({
        ...validConfig,
        logsDiagnosticsConfigEmitPolicy: '{"emit":"off"}',
      });

      expect(result.logsDiagnosticsConfigEmitPolicy).toEqual({ emit: 'off' });
    });

    it('rejects empty events array when emit is on', () => {
      expect(() =>
        AppConfigSchema.parse({
          ...validConfig,
          logsDiagnosticsConfigEmitPolicy: '{"emit":"on","events":[]}',
        }),
      ).toThrow();
    });

    it('rejects missing events when emit is on', () => {
      expect(() =>
        AppConfigSchema.parse({
          ...validConfig,
          logsDiagnosticsConfigEmitPolicy: '{"emit":"on"}',
        }),
      ).toThrow();
    });

    it('accepts a native object value', () => {
      const result = AppConfigSchema.parse({
        ...validConfig,
        logsDiagnosticsConfigEmitPolicy: {
          emit: 'on',
          events: [ConfigEmitEvent.PER_SYNC],
        },
      });

      expect(result.logsDiagnosticsConfigEmitPolicy).toEqual({
        emit: 'on',
        events: ['per_sync'],
      });
    });

    it('rejects invalid enum values in events array', () => {
      expect(() =>
        AppConfigSchema.parse({
          ...validConfig,
          logsDiagnosticsConfigEmitPolicy: '{"emit":"on","events":["invalid"]}',
        }),
      ).toThrow();
    });

    it('rejects an invalid emit value', () => {
      expect(() =>
        AppConfigSchema.parse({
          ...validConfig,
          logsDiagnosticsConfigEmitPolicy: '{"emit":"maybe"}',
        }),
      ).toThrow();
    });

    it('rejects old format "none" string', () => {
      expect(() =>
        AppConfigSchema.parse({
          ...validConfig,
          logsDiagnosticsConfigEmitPolicy: 'none',
        }),
      ).toThrow();
    });

    it('rejects old format JSON array string', () => {
      expect(() =>
        AppConfigSchema.parse({
          ...validConfig,
          logsDiagnosticsConfigEmitPolicy: '["on_startup"]',
        }),
      ).toThrow();
    });
  });

  describe('tenantConfigPathPattern', () => {
    it('rejects an empty string', () => {
      expect(() =>
        AppConfigSchema.parse({ ...validConfig, tenantConfigPathPattern: '' }),
      ).toThrow();
    });

    it('rejects a whitespace-only string', () => {
      expect(() =>
        AppConfigSchema.parse({ ...validConfig, tenantConfigPathPattern: '   ' }),
      ).toThrow();
    });
  });

  describe('transform', () => {
    it('adds isDev true when nodeEnv is development', () => {
      const result = AppConfigSchema.parse({ ...validConfig, nodeEnv: 'development' });

      expect(result.isDev).toBe(true);
    });

    it('adds isDev false when nodeEnv is production', () => {
      const result = AppConfigSchema.parse({ ...validConfig, nodeEnv: 'production' });

      expect(result.isDev).toBe(false);
    });
  });
});
