import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { Redacted } from '../utils/redacted';
import type { Config } from './index';

@Injectable()
export class ConfigDiagnosticsService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly configService: ConfigService<Config, true>) {}

  public async onModuleInit() {
    await ConfigModule.envVariablesLoaded;

    const emitPolicy = this.configService.get('app.logsDiagnosticsConfigEmitPolicy', {
      infer: true,
    });
    if (emitPolicy === 'none') {
      return;
    }

    this.logger.log('Emitting configuration on startup:');
    this.logConfig('App Config', this.configService.get('app', { infer: true }));
    this.logConfig('SharePoint Config', this.configService.get('sharepoint', { infer: true }));
    this.logConfig('Unique Config', this.configService.get('unique', { infer: true }));
    this.logConfig('Processing Config', this.configService.get('processing', { infer: true }));
  }

  public logConfig(name: string, value: unknown) {
    const emitPolicy = this.configService.get('app.logsDiagnosticsConfigEmitPolicy', {
      infer: true,
    });
    if (emitPolicy === 'none') {
      return;
    }

    const filteredValue = filterRedactedFields(value);
    this.logger.log({
      msg: `Configuration: ${name}`,
      config: filteredValue,
    });
  }
}

/**
 * Recursively filters out Redacted fields from an object or array.
 * Useful for logging configuration without revealing secret field names.
 */
export function filterRedactedFields(value: unknown): unknown {
  if (value instanceof Redacted) {
    return undefined;
  }

  if (Array.isArray(value)) {
    return value.map(filterRedactedFields).filter((item) => item !== undefined);
  }

  if (value !== null && typeof value === 'object') {
    const filtered: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      const filteredVal = filterRedactedFields(val);
      if (filteredVal !== undefined) {
        filtered[key] = filteredVal;
      }
    }
    return filtered;
  }

  return value;
}
