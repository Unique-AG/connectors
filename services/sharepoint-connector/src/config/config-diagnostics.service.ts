import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { ConfigEmitPolicy, type ConfigEmitPolicyType } from './app.config';
import type { Config } from './index';

@Injectable()
export class ConfigDiagnosticsService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly configService: ConfigService<Config, true>) {}

  public async onModuleInit() {
    await ConfigModule.envVariablesLoaded;

    if (!this.shouldLogConfig(ConfigEmitPolicy.ON_STARTUP)) {
      return;
    }
    this.logConfig('App Config', this.configService.get('app', { infer: true }));
    this.logConfig('SharePoint Config', this.configService.get('sharepoint', { infer: true }));
    this.logConfig('Unique Config', this.configService.get('unique', { infer: true }));
    this.logConfig('Processing Config', this.configService.get('processing', { infer: true }));
  }

  public shouldLogConfig(configEmitPolicy: ConfigEmitPolicyType): boolean {
    const emitPolicy = this.configService.get('app.logsDiagnosticsConfigEmitPolicy', {
      infer: true,
    });
    return emitPolicy !== 'none' && emitPolicy.includes(configEmitPolicy);
  }

  public logConfig(msg: string, config: object) {
    this.logger.log({
      msg,
      config,
    });
  }
}
