import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { shouldConcealLogs } from '../utils/logging.util';
import { Redacted } from '../utils/redacted';
import type { Config } from './index';

@Injectable()
export class ConfigDiagnosticsService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly configService: ConfigService<Config, true>) {}

  public async onModuleInit() {
    await ConfigModule.envVariablesLoaded;

    // Configure the Redacted class to respect the diagnostic data policy
    Redacted.setConceal(shouldConcealLogs(this.configService));

    const emitPolicy = this.configService.get('app.logsDiagnosticsConfigEmitPolicy', {
      infer: true,
    });
    if (emitPolicy === 'none') {
      return;
    }

    this.logger.log('Emitting effective configuration on startup...');

    this.logConfig('App Config', this.configService.get('app', { infer: true }));
    this.logConfig('SharePoint Config', this.configService.get('sharepoint', { infer: true }));
    this.logConfig('Unique Config', this.configService.get('unique', { infer: true }));
    this.logConfig('Processing Config', this.configService.get('processing', { infer: true }));
  }

  /**
   * Logs the configuration. Redacted fields will handle their own redaction via toJSON().
   */
  public logConfig(name: string, value: unknown) {
    const emitPolicy = this.configService.get('app.logsDiagnosticsConfigEmitPolicy', {
      infer: true,
    });
    if (emitPolicy === 'none') {
      return;
    }

    this.logger.log({
      msg: `Effective configuration: ${name}`,
      config: value,
    });
  }
}
