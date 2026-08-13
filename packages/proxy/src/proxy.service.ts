import { readFileSync } from 'node:fs';
import type * as http from 'node:http';
import { Inject, Injectable, Logger, type OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { HttpsProxyAgent } from 'https-proxy-agent';
import { Agent, type Dispatcher, ProxyAgent } from 'undici';
import {
  type BasicProxyConfig,
  type NoAuthProxyConfig,
  type ProxyConfig,
  type ProxyConfigNamespaced,
  type TlsProxyConfig,
} from './proxy.config';
import { PROXY_MODULE_OPTIONS_TOKEN, type ProxyModuleOptions } from './proxy.module-definition';

export type ProxyMode = 'always' | 'never' | 'for-external-only';

export interface GetDispatcherOptions {
  mode: ProxyMode;
}

export interface GetHttpAgentOptions {
  mode: ProxyMode;
}

@Injectable()
export class ProxyService implements OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly dispatcher: Dispatcher;
  private readonly noProxyDispatcher: Dispatcher;
  private readonly httpAgent: http.Agent | undefined;
  private readonly isExternal: boolean;

  private static readonly sharedTimeoutOptions = {
    bodyTimeout: 60_000,
    headersTimeout: 30_000,
    connectTimeout: 15_000,
  };

  public constructor(
    @Inject(PROXY_MODULE_OPTIONS_TOKEN)
    options: ProxyModuleOptions,
    configService: ConfigService<ProxyConfigNamespaced, true>,
  ) {
    const proxyConfig = configService.get('proxy', { infer: true });

    this.isExternal = options.isExternal;
    this.noProxyDispatcher = new Agent(ProxyService.sharedTimeoutOptions);
    this.dispatcher = this.createDispatcher(proxyConfig);
    this.httpAgent = this.createHttpAgent(proxyConfig);

    this.logger.log({
      msg: 'ProxyService initialized',
      authMode: proxyConfig.authMode,
      isExternal: this.isExternal,
    });
  }

  public getDispatcher({ mode }: GetDispatcherOptions): Dispatcher {
    if (!this.shouldUseProxy(mode)) {
      return this.noProxyDispatcher;
    }
    return this.dispatcher;
  }

  public getHttpAgent({ mode }: GetHttpAgentOptions): http.Agent | undefined {
    if (!this.shouldUseProxy(mode) || this.httpAgent === undefined) {
      return undefined;
    }
    return this.httpAgent;
  }

  public async onModuleDestroy(): Promise<void> {
    await this.dispatcher.close();
    await this.noProxyDispatcher.close();
    this.httpAgent?.destroy();
  }

  private shouldUseProxy(mode: ProxyMode): boolean {
    if (mode === 'never') {
      return false;
    }
    if (mode === 'always') {
      return true;
    }
    return this.isExternal;
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
        `${proxyConfig.username.value}:${proxyConfig.password.value}`,
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
      proxyOptions.headers = { ...proxyConfig.headers };
    }

    this.logger.log({
      msg: 'Created ProxyAgent',
      proxyUrl,
      authMode: proxyConfig.authMode,
    });

    return new ProxyAgent(proxyOptions);
  }

  private createHttpAgent(proxyConfig: ProxyConfig): http.Agent | undefined {
    if (proxyConfig.authMode === 'none') {
      return undefined;
    }

    const proxyUrl =
      proxyConfig.authMode === 'username_password'
        ? this.buildAuthenticatedProxyUrl(proxyConfig)
        : this.buildProxyUrl(proxyConfig);

    const agentOptions: {
      ca?: Buffer;
      cert?: Buffer;
      key?: Buffer;
      headers?: Record<string, string>;
    } = {};

    if (proxyConfig.sslCaBundlePath) {
      agentOptions.ca = readFileSync(proxyConfig.sslCaBundlePath);
    }

    if (proxyConfig.authMode === 'ssl_tls') {
      agentOptions.cert = readFileSync(proxyConfig.sslCertPath);
      agentOptions.key = readFileSync(proxyConfig.sslKeyPath);
    }

    if (proxyConfig.headers) {
      agentOptions.headers = { ...proxyConfig.headers };
    }

    this.logger.log({
      msg: 'Created HttpsProxyAgent',
      proxyUrl: this.buildProxyUrl(proxyConfig),
      authMode: proxyConfig.authMode,
    });

    return new HttpsProxyAgent(proxyUrl, agentOptions);
  }

  private buildProxyUrl(
    proxyConfig: NoAuthProxyConfig | BasicProxyConfig | TlsProxyConfig,
  ): string {
    return `${proxyConfig.protocol}://${proxyConfig.host}:${proxyConfig.port}`;
  }

  private buildAuthenticatedProxyUrl(proxyConfig: BasicProxyConfig): string {
    const username = encodeURIComponent(proxyConfig.username.value);
    const password = encodeURIComponent(proxyConfig.password.value);
    return `${proxyConfig.protocol}://${username}:${password}@${proxyConfig.host}:${proxyConfig.port}`;
  }
}
