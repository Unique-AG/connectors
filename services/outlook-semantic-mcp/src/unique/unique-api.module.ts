import assert from 'node:assert';
import { ProxyService } from '@unique-ag/proxy';
import {
  getUniqueApiClientToken,
  UniqueApiClient,
  UniqueApiFeatureModuleInputOptions,
  UniqueApiModule,
} from '@unique-ag/unique-api';
import { type DynamicModule, Inject, Module, type Provider } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { interceptors } from 'undici';
import {
  IngestionConfigNamespaced,
  loadFeaturesConfig,
  UNIQUE_REQUIRED_BY,
  UniqueConfigNamespaced,
} from '../config';
import { UploadFileForIngestionCommand } from './upload-file-for-ingestion.command';

const OUTLOOK_SEMANTIC_MCP_TOKEN_NAME = 'outlook-semantic-mcp';
const UNIQUE_API_CLIENT_TOKEN = getUniqueApiClientToken(OUTLOOK_SEMANTIC_MCP_TOKEN_NAME);

export const InjectUniqueApi = () => Inject(UNIQUE_API_CLIENT_TOKEN);

export const uniqueApiFeatureOptionsFactory = (
  configService: ConfigService<UniqueConfigNamespaced & IngestionConfigNamespaced, true>,
  proxyService: ProxyService,
): UniqueApiFeatureModuleInputOptions => {
  const uniqueConfig = configService.get('unique', { infer: true });
  assert.ok(uniqueConfig.enabled, 'The Unique API client is built only when Unique is needed');
  const ingestionCfg = configService.get('ingestion', { infer: true });
  return {
    auth:
      uniqueConfig.serviceAuthMode === 'cluster_local'
        ? { ...uniqueConfig, serviceId: 'outlook-semantic-mcp' }
        : uniqueConfig,
    ingestion: { baseUrl: uniqueConfig.ingestionServiceBaseUrl },
    scopeManagement: { baseUrl: uniqueConfig.scopeManagementServiceBaseUrl },
    healthCheckTimeoutMs: ingestionCfg.connectivityTimeoutMs,
    dispatcher: proxyService
      .getDispatcher({ mode: 'for-external-only' })
      .compose([interceptors.retry(), interceptors.redirect()]),
  };
};

const UNIQUE_API_FEATURE_MODULE = UniqueApiModule.forFeatureAsync(OUTLOOK_SEMANTIC_MCP_TOKEN_NAME, {
  imports: [ConfigModule],
  inject: [ConfigService, ProxyService],
  useFactory: uniqueApiFeatureOptionsFactory,
});

// Injected wherever the Unique client is when no enabled feature needs Unique, so the real client
// and its config are never built. Code that can run then must not touch it.
export class UnavailableUniqueApiClient extends UniqueApiClient {
  public get auth(): never {
    return unavailable('auth');
  }
  public get health(): never {
    return unavailable('health');
  }
  public get scopes(): never {
    return unavailable('scopes');
  }
  public get files(): never {
    return unavailable('files');
  }
  public get users(): never {
    return unavailable('users');
  }
  public get groups(): never {
    return unavailable('groups');
  }
  public get ingestion(): never {
    return unavailable('ingestion');
  }
  public get content(): never {
    return unavailable('content');
  }
}

function unavailable(facade: string): never {
  assert.fail(
    `The Unique API client was used (${facade}) although no enabled feature needs Unique. Unique is needed by ${UNIQUE_REQUIRED_BY}.`,
  );
}

const uniqueApiClient: {
  imports: DynamicModule[];
  providers: Provider[];
  exports: (DynamicModule | string)[];
} = loadFeaturesConfig().unique
  ? { imports: [UNIQUE_API_FEATURE_MODULE], providers: [], exports: [UNIQUE_API_FEATURE_MODULE] }
  : {
      imports: [],
      providers: [{ provide: UNIQUE_API_CLIENT_TOKEN, useClass: UnavailableUniqueApiClient }],
      exports: [UNIQUE_API_CLIENT_TOKEN],
    };

@Module({
  imports: [ConfigModule, ...uniqueApiClient.imports],
  providers: [...uniqueApiClient.providers, UploadFileForIngestionCommand],
  exports: [...uniqueApiClient.exports, UploadFileForIngestionCommand],
})
export class UniqueApiFeatureModule {}
