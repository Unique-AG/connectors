import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../utils/redacted';
import { ConfigDiagnosticsService, filterRedactedFields } from './config-diagnostics.service';

vi.mock('@nestjs/config', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/config')>();
  return {
    ...actual,
    ConfigModule: {
      envVariablesLoaded: Promise.resolve(),
    },
  };
});

describe('ConfigDiagnosticsService', () => {
  let service: ConfigDiagnosticsService;
  let configService: ConfigService;
  let loggerSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(async () => {
    const { unit, unitRef } = await TestBed.solitary(ConfigDiagnosticsService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn(),
      }))
      .compile();

    service = unit;
    // biome-ignore lint/suspicious/noExplicitAny: Mock ConfigService for testing
    configService = unitRef.get(ConfigService) as any;
    // biome-ignore lint/suspicious/noExplicitAny: access private logger for testing
    loggerSpy = vi.spyOn((service as any).logger, 'log');
  });

  describe('logConfig', () => {
    it('logs configuration when emit policy is on_startup', () => {
      vi.spyOn(configService, 'get').mockReturnValue('on_startup');

      const config = { foo: 'bar' };
      service.logConfig('Test', config);

      expect(loggerSpy).toHaveBeenCalledWith({
        msg: 'Configuration: Test',
        config: { foo: 'bar' },
      });
    });

    it('skips logging when emit policy is none', () => {
      vi.spyOn(configService, 'get').mockReturnValue('none');

      service.logConfig('Test', { foo: 'bar' });

      expect(loggerSpy).not.toHaveBeenCalled();
    });

    it('filters out Redacted fields from the logged configuration', () => {
      vi.spyOn(configService, 'get').mockReturnValue('on_startup');

      const config = {
        public: 'info',
        secret: new Redacted('sensitive'),
        nested: {
          key: new Redacted('deep-secret'),
          other: 'visible',
        },
        list: ['public', new Redacted('secret-item')],
      };

      service.logConfig('Test', config);

      expect(loggerSpy).toHaveBeenCalledWith({
        msg: 'Configuration: Test',
        config: {
          public: 'info',
          nested: {
            other: 'visible',
          },
          list: ['public'],
        },
      });
    });
  });

  describe('filterRedactedFields', () => {
    it('returns non-redacted values as is', () => {
      expect(filterRedactedFields('test')).toBe('test');
      expect(filterRedactedFields(123)).toBe(123);
      expect(filterRedactedFields(true)).toBe(true);
      expect(filterRedactedFields(null)).toBe(null);
    });

    it('returns undefined for Redacted instance', () => {
      const redacted = new Redacted('secret');
      expect(filterRedactedFields(redacted)).toBeUndefined();
    });

    it('filters out Redacted fields from objects', () => {
      const config = {
        apiKey: new Redacted('secret'),
        public: 'info',
      };
      expect(filterRedactedFields(config)).toEqual({ public: 'info' });
    });

    it('filters out Redacted items from arrays', () => {
      const list = ['public', new Redacted('secret'), 'more-public'];
      expect(filterRedactedFields(list)).toEqual(['public', 'more-public']);
    });

    it('filters nested objects and arrays', () => {
      const complexConfig = {
        app: {
          name: 'test-app',
          secrets: [new Redacted('s1'), 'not-a-secret'],
        },
        auth: {
          token: new Redacted('t1'),
          clientId: 'id1',
        },
      };

      expect(filterRedactedFields(complexConfig)).toEqual({
        app: {
          name: 'test-app',
          secrets: ['not-a-secret'],
        },
        auth: {
          clientId: 'id1',
        },
      });
    });

    it('handles empty objects and arrays after filtering', () => {
      const config = {
        secret: new Redacted('s1'),
      };
      expect(filterRedactedFields(config)).toEqual({});

      const list = [new Redacted('s1')];
      expect(filterRedactedFields(list)).toEqual([]);
    });
  });

  describe('onModuleInit', () => {
    it('emits all configurations when policy is on_startup', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy') return 'on_startup';
        return { some: 'config' };
      });

      await service.onModuleInit();

      // Should be called 1 time for "Emitting configuration on startup:"
      // and 4 times for each config section (App, SharePoint, Unique, Processing)
      expect(loggerSpy).toHaveBeenCalledTimes(5);
      expect(loggerSpy).toHaveBeenCalledWith('Emitting configuration on startup:');
    });

    it('skips emitting configurations when policy is none', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy') return 'none';
        return { some: 'config' };
      });

      await service.onModuleInit();

      expect(loggerSpy).not.toHaveBeenCalled();
    });
  });
});
