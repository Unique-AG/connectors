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

// The caller (TenantRegistry) decides the mode per request based on each tenant's serviceAuthMode.
// With the current config it's technically possible for one tenant to use cluster_local while
// another uses external. Rather than baking that logic into ProxyService (which is pure
// infrastructure), we keep the decision at the call site so every combination works.
export type ProxyMode = 'always' | 'never';

export interface GetDispatcherOptions {
  mode: ProxyMode;
}

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

  public getDispatcher({ mode }: GetDispatcherOptions): Dispatcher {
    if (mode === 'never') {
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
