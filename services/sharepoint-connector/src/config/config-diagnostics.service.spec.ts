import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../utils/redacted';
import { ConfigEmitEvent } from './app.config';
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
    it('returns true when policy includes the requested event', () => {
      vi.spyOn(configService, 'get').mockReturnValue({
        emit: 'on',
        events: [ConfigEmitEvent.ON_STARTUP],
      });

      expect(service.shouldLogConfig(ConfigEmitEvent.ON_STARTUP)).toBe(true);
    });

    it('returns false when policy does not include the requested event', () => {
      vi.spyOn(configService, 'get').mockReturnValue({
        emit: 'on',
        events: [ConfigEmitEvent.ON_SYNC],
      });

      expect(service.shouldLogConfig(ConfigEmitEvent.ON_STARTUP)).toBe(false);
    });

    it('returns true when policy includes both events and requesting either', () => {
      vi.spyOn(configService, 'get').mockReturnValue({
        emit: 'on',
        events: [ConfigEmitEvent.ON_STARTUP, ConfigEmitEvent.ON_SYNC],
      });

      expect(service.shouldLogConfig(ConfigEmitEvent.ON_STARTUP)).toBe(true);
      expect(service.shouldLogConfig(ConfigEmitEvent.ON_SYNC)).toBe(true);
    });

    it('returns false when emit is off', () => {
      vi.spyOn(configService, 'get').mockReturnValue({ emit: 'off' });

      expect(service.shouldLogConfig(ConfigEmitEvent.ON_STARTUP)).toBe(false);
      expect(service.shouldLogConfig(ConfigEmitEvent.ON_SYNC)).toBe(false);
    });
  });

  describe('onModuleInit', () => {
    it('emits all configurations when emit is on with on_startup event', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy')
          return { emit: 'on', events: [ConfigEmitEvent.ON_STARTUP] };
        return { some: 'config' };
      });

      await service.onModuleInit();

      expect(loggerSpy).toHaveBeenCalledTimes(4);
    });

    it('emits all configurations when emit is on with both events', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy')
          return {
            emit: 'on',
            events: [ConfigEmitEvent.ON_STARTUP, ConfigEmitEvent.ON_SYNC],
          };
        return { some: 'config' };
      });

      await service.onModuleInit();

      expect(loggerSpy).toHaveBeenCalledTimes(4);
    });

    it('skips emitting configurations when emit is off', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy') return { emit: 'off' };
        return { some: 'config' };
      });

      await service.onModuleInit();

      expect(loggerSpy).not.toHaveBeenCalled();
    });

    it('skips emitting configurations when emit is on with only on_sync event', async () => {
      vi.spyOn(configService, 'get').mockImplementation((key) => {
        if (key === 'app.logsDiagnosticsConfigEmitPolicy')
          return { emit: 'on', events: [ConfigEmitEvent.ON_SYNC] };
        return { some: 'config' };
      });

      await service.onModuleInit();

      expect(loggerSpy).not.toHaveBeenCalled();
    });
  });
});
