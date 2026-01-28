import { readFileSync } from 'node:fs';
import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Agent, Dispatcher, ProxyAgent } from 'undici';
import { Config } from '../config';
import { BasicProxyConfig, ProxyConfig, TlsProxyConfig } from '../config/proxy.schema';

export type ProxyMode = 'always' | 'external-only';

@Injectable()
export class ProxyService implements OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly dispatcher: Dispatcher;
  private readonly noProxyDispatcher: Dispatcher;
  private readonly isExternalMode: boolean;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const proxyConfig = this.configService.get('proxy', { infer: true });
    const uniqueConfig = this.configService.get('unique', { infer: true });

    this.isExternalMode = uniqueConfig.serviceAuthMode === 'external';
    this.noProxyDispatcher = new Agent();
    this.dispatcher = this.createDispatcher(proxyConfig);

    this.logger.log({
      msg: 'ProxyService initialized',
      authMode: proxyConfig.authMode,
      isExternalMode: this.isExternalMode,
    });
  }

  public getDispatcher(mode: ProxyMode): Dispatcher {
    if (mode === 'external-only' && !this.isExternalMode) {
      return this.noProxyDispatcher;
    }
    return this.dispatcher;
  }

  public async onModuleDestroy(): Promise<void> {
    await this.dispatcher.close();
    await this.noProxyDispatcher.close();
  }

  private createDispatcher(proxyConfig: ProxyConfig): Dispatcher {
    const sharedOptions = {
      bodyTimeout: 60_000,
      headersTimeout: 30_000,
      connectTimeout: 15_000,
    };

    if (proxyConfig.authMode === 'none') {
      return new Agent(sharedOptions);
    }

    const proxyUrl = this.buildProxyUrl(proxyConfig);
    const proxyOptions: ProxyAgent.Options = {
      uri: proxyUrl,
      ...sharedOptions,
    };

    if (proxyConfig.authMode === 'basic') {
      const credentials = Buffer.from(`${proxyConfig.username}:${proxyConfig.password}`).toString(
        'base64',
      );
      proxyOptions.token = `Basic ${credentials}`;
    }

    if (proxyConfig.authMode === 'tls') {
      proxyOptions.requestTls = {
        cert: readFileSync(proxyConfig.tlsCertPath),
        key: readFileSync(proxyConfig.tlsKeyPath),
      };
    }

    if (proxyConfig.caBundlePath) {
      proxyOptions.proxyTls = { ca: readFileSync(proxyConfig.caBundlePath) };
    }

    if (proxyConfig.headers) {
      proxyOptions.headers = proxyConfig.headers;
    }

    this.logger.log({
      msg: 'Created ProxyAgent',
      proxyUrl,
      authMode: proxyConfig.authMode,
    });

    return new ProxyAgent(proxyOptions);
  }

  private buildProxyUrl(proxyConfig: BasicProxyConfig | TlsProxyConfig): string {
    return `${proxyConfig.protocol}://${proxyConfig.host}:${proxyConfig.port}`;
  }
}
