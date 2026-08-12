import { ProxyService } from '@unique-ag/proxy';
import {
  getUniqueApiClientToken,
  UniqueApiFeatureModuleInputOptions,
  UniqueApiModule,
} from '@unique-ag/unique-api';
import { Inject, Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { interceptors } from 'undici';
import { IngestionConfigNamespaced, UniqueConfigNamespaced } from '../config';
import { UploadFileForIngestionCommand } from './upload-file-for-ingestion.command';

const OUTLOOK_SEMANTIC_MCP_TOKEN_NAME = 'outlook-semantic-mcp';

export const InjectUniqueApi = () =>
  Inject(getUniqueApiClientToken(OUTLOOK_SEMANTIC_MCP_TOKEN_NAME));

export const uniqueApiFeatureOptionsFactory = (
  configService: ConfigService<UniqueConfigNamespaced & IngestionConfigNamespaced, true>,
  proxyService: ProxyService,
): UniqueApiFeatureModuleInputOptions => {
  const uniqueConfig = configService.get('unique', { infer: true });
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

@Module({
  imports: [ConfigModule, UNIQUE_API_FEATURE_MODULE],
  providers: [UploadFileForIngestionCommand],
  exports: [UNIQUE_API_FEATURE_MODULE, UploadFileForIngestionCommand],
})
export class UniqueApiFeatureModule {}
