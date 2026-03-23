import { readFileSync } from 'node:fs';
import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Agent, Dispatcher, ProxyAgent } from 'undici';
import {
  type BasicProxyConfig,
  type NoAuthProxyConfig,
  type ProxyConfig,
  type ProxyConfigNamespaced,
  type TlsProxyConfig,
} from '../config';

export type ProxyMode = 'always' | 'for-external-only';

export type GetDispatcherOptions =
  | { mode: 'always' }
  | { mode: 'for-external-only'; isExternal: boolean };

@Injectable()
export class ProxyService implements OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly dispatcher: Dispatcher;
  private readonly noProxyDispatcher: Dispatcher;

  private static readonly sharedTimeoutOptions = {
    bodyTimeout: 60_000,
    headersTimeout: 30_000,
    connectTimeout: 15_000,
  };

  public constructor(configService: ConfigService<ProxyConfigNamespaced, true>) {
    const proxyConfig = configService.get('proxy', { infer: true });

    this.noProxyDispatcher = new Agent(ProxyService.sharedTimeoutOptions);
    this.dispatcher = this.createDispatcher(proxyConfig);

    this.logger.log({
      msg: 'ProxyService initialized',
      authMode: proxyConfig.authMode,
    });
  }

  public getDispatcher(options: GetDispatcherOptions): Dispatcher {
    if (options.mode === 'for-external-only' && !options.isExternal) {
      return this.noProxyDispatcher;
    }
    return this.dispatcher;
  }

  public async onModuleDestroy(): Promise<void> {
    await this.dispatcher.close();
    await this.noProxyDispatcher.close();
  }

  private createDispatcher(proxyConfig: ProxyConfig): Dispatcher {
    if (proxyConfig.authMode === 'none') {
      return new Agent(ProxyService.sharedTimeoutOptions);
    }

    const proxyUrl = this.buildProxyUrl(proxyConfig);
    const proxyOptions: ProxyAgent.Options = {
      uri: proxyUrl,
      ...ProxyService.sharedTimeoutOptions,
    };

    if (proxyConfig.authMode === 'username_password') {
      const credentials = Buffer.from(
        `${proxyConfig.username}:${proxyConfig.password.value}`,
      ).toString('base64');
      proxyOptions.token = `Basic ${credentials}`;
    }

    if (proxyConfig.sslCaBundlePath) {
      proxyOptions.proxyTls = { ca: readFileSync(proxyConfig.sslCaBundlePath) };
    }

    if (proxyConfig.authMode === 'ssl_tls') {
      proxyOptions.proxyTls = {
        ...(proxyOptions.proxyTls ?? {}),
        cert: readFileSync(proxyConfig.sslCertPath),
        key: readFileSync(proxyConfig.sslKeyPath),
      };
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

  private buildProxyUrl(
    proxyConfig: NoAuthProxyConfig | BasicProxyConfig | TlsProxyConfig,
  ): string {
    return `${proxyConfig.protocol}://${proxyConfig.host}:${proxyConfig.port}`;
  }
}
