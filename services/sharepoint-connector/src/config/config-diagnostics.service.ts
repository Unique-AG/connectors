import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { ConfigEmitEvent, type ConfigEmitEventType } from './app.config';
import type { Config } from './index';

@Injectable()
export class ConfigDiagnosticsService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly configService: ConfigService<Config, true>) {}

  public async onModuleInit() {
    await ConfigModule.envVariablesLoaded;

    if (!this.shouldLogConfig(ConfigEmitEvent.ON_STARTUP)) {
      return;
    }
    this.logConfig('App Config', this.configService.get('app', { infer: true }));
    this.logConfig('SharePoint Config', this.configService.get('sharepoint', { infer: true }));
    this.logConfig('Unique Config', this.configService.get('unique', { infer: true }));
    this.logConfig('Processing Config', this.configService.get('processing', { infer: true }));
  }

  public shouldLogConfig(event: ConfigEmitEventType): boolean {
    const policy = this.configService.get('app.logsDiagnosticsConfigEmitPolicy', {
      infer: true,
    });
    return policy.emit === 'on' && policy.events.includes(event);
  }

  public logConfig(msg: string, config: object) {
    this.logger.log({
      msg,
      config,
    });
  }
}
