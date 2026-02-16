import type { DynamicModule, InjectionToken, Type } from '@nestjs/common';
import type { Dispatcher } from 'undici';
import type { UniqueApiClientAuthConfig } from './unique-api-auth-config.types';

export interface UniqueApiClientConfig {
  auth: UniqueApiClientAuthConfig;
  endpoints: {
    scopeManagementBaseUrl: string;
    ingestionBaseUrl: string;
  };
  rateLimitPerMinute?: number;
  dispatcher?: Dispatcher;
  metadata?: {
    clientName?: string;
    tenantKey?: string;
  };
}

export interface UniqueApiObservabilityConfig {
  loggerContext?: string;
  metricPrefix?: string;
}

export interface UniqueApiModuleOptions {
  observability?: UniqueApiObservabilityConfig;
}

export interface UniqueApiModuleAsyncOptions {
  imports?: Array<Type<unknown> | DynamicModule>;
  inject?: InjectionToken[];
  useFactory: (...args: never[]) => UniqueApiModuleOptions | Promise<UniqueApiModuleOptions>;
}

export interface UniqueApiFeatureAsyncOptions {
  imports?: Array<Type<unknown> | DynamicModule>;
  inject?: InjectionToken[];
  useFactory: (...args: never[]) => UniqueApiClientConfig | Promise<UniqueApiClientConfig>;
}
