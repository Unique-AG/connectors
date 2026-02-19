import {
  getUniqueApiClientToken,
  UniqueApiFeatureModuleInputOptions,
  UniqueApiModule,
} from '@unique-ag/unique-api';
import { Inject, Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { HttpClientModule, HttpClientService } from '~/http-client/http-client.service';
import { UniqueConfig, uniqueConfig } from '../config';
import { UploadFileForIngestionCommand } from './upload-file-for-ingestion.command';

const OUTLOOK_SEMANTIC_MCP_TOKEN_NAME = 'outlook-semantic-mcp';

export const InjectUniqueApi = () =>
  Inject(getUniqueApiClientToken(OUTLOOK_SEMANTIC_MCP_TOKEN_NAME));

const UNIQUE_API_FEATURE_MODULE = UniqueApiModule.forFeatureAsync(OUTLOOK_SEMANTIC_MCP_TOKEN_NAME, {
  imports: [ConfigModule],
  inject: [uniqueConfig.KEY],
  useFactory: (config: UniqueConfig): UniqueApiFeatureModuleInputOptions => {
    return {
      auth: config,
      ingestion: { baseUrl: config.ingestionServiceBaseUrl },
      scopeManagment: { baseUrl: config.scopeManagementServiceBaseUrl },
    };
  },
});

@Module({
  imports: [ConfigModule, UNIQUE_API_FEATURE_MODULE, HttpClientModule],
  providers: [
    {
      inject: [uniqueConfig.KEY, HttpClientService],
      provide: UploadFileForIngestionCommand,
      useFactory: (
        config: UniqueConfig,
        service: HttpClientService,
      ): UploadFileForIngestionCommand => {
        return new UploadFileForIngestionCommand(config, service);
      },
    },
  ],
  exports: [UNIQUE_API_FEATURE_MODULE, UploadFileForIngestionCommand],
})
export class UniqueApiFeatureModule {}
