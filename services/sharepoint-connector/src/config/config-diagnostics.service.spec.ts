import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../utils/redacted';
import { ConfigEmitPolicy } from './app.config';
import { ConfigDiagnosticsService } from './config-diagnostics.service';

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
    it('logs configuration', () => {
      const config = { foo: 'bar' };
      service.logConfig('Test', config);

      expect(loggerSpy).toHaveBeenCalledWith({
        msg: 'Test',
        config: { foo: 'bar' },
      });
    });

    it('logs configuration with Redacted fields serialized via toJSON', () => {
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
        msg: 'Test',
        config: {
          public: 'info',
          secret: new Redacted('sensitive'),
          nested: {
            key: new Redacted('deep-secret'),
            other: 'visible',
          },
          list: ['public', new Redacted('secret-item')],
        },
      });
    });
  });

  describe('shouldLogConfig', () => {
    it('returns true when policy includes the requested emit policy', () => {
      vi.spyOn(configService, 'get').mockReturnValue([ConfigEmitPolicy.ON_STARTUP]);

      expect(service.shouldLogConfig(ConfigEmitPolicy.ON_STARTUP)).toBe(true);
    });

    it('returns false when policy does not include the requested emit policy', () => {
      vi.spyOn(configService, 'get').mockReturnValue([ConfigEmitPolicy.PER_SYNC]);

      expect(service.shouldLogConfig(ConfigEmitPolicy.ON_STARTUP)).toBe(false);
    });

    it('returns true when policy includes both and requesting either', () => {
      vi.spyOn(configService, 'get').mockReturnValue([
        ConfigEmitPolicy.ON_STARTUP,
        ConfigEmitPolicy.PER_SYNC,
      ]);

      expect(service.shouldLogConfig(ConfigEmitPolicy.ON_STARTUP)).toBe(true);
      expect(service.shouldLogConfig(ConfigEmitPolicy.PER_SYNC)).toBe(true);
    });

    it('returns false when policy is none', () => {
      vi.spyOn(configService, 'get').mockReturnValue('none');

      expect(service.shouldLogConfig(ConfigEmitPolicy.ON_STARTUP)).toBe(false);
      expect(service.shouldLogConfig(ConfigEmitPolicy.PER_SYNC)).toBe(false);
    });
  });

  describe('onModuleInit', () => {
    it('emits all configurations when policy includes on_startup', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy') return [ConfigEmitPolicy.ON_STARTUP];
        return { some: 'config' };
      });

      await service.onModuleInit();

      // Should be called 4 times for each config section (App, SharePoint, Unique, Processing)
      expect(loggerSpy).toHaveBeenCalledTimes(4);
    });

    it('emits all configurations when policy includes both on_startup and per_sync', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy')
          return [ConfigEmitPolicy.ON_STARTUP, ConfigEmitPolicy.PER_SYNC];
        return { some: 'config' };
      });

      await service.onModuleInit();

      expect(loggerSpy).toHaveBeenCalledTimes(4);
    });

    it('skips emitting configurations when policy is none', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy') return 'none';
        return { some: 'config' };
      });

      await service.onModuleInit();

      expect(loggerSpy).not.toHaveBeenCalled();
    });

    it('skips emitting configurations when policy only includes per_sync', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy') return [ConfigEmitPolicy.PER_SYNC];
        return { some: 'config' };
      });

      await service.onModuleInit();

      expect(loggerSpy).not.toHaveBeenCalled();
    });
  });
});
