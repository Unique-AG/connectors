import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import type { Config } from './index';
import type { SiteConfig } from './sharepoint.schema';

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
    this.logAllConfigs();
  }

  public logAllConfigs(): void {
    this.logConfig('App Config', this.configService.get('app', { infer: true }));
    this.logConfig('SharePoint Config', this.configService.get('sharepoint', { infer: true }));
    this.logConfig('Unique Config', this.configService.get('unique', { infer: true }));
    this.logConfig('Processing Config', this.configService.get('processing', { infer: true }));
  }

  public logSiteConfig(siteConfig: SiteConfig, label: string = 'Site Config'): void {
    this.logConfig(label, siteConfig);
  }

  public logConfig(name: string, value: unknown) {
    const emitPolicy = this.configService.get('app.logsDiagnosticsConfigEmitPolicy', {
      infer: true,
    });
    if (emitPolicy === 'none') {
      return;
    }

    this.logger.log({
      msg: `Configuration: ${name}`,
      config: value,
    });
  }
}
