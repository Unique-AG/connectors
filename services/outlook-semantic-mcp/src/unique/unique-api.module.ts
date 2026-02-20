import {
  getUniqueApiClientToken,
  UniqueApiFeatureModuleInputOptions,
  UniqueApiModule,
} from '@unique-ag/unique-api';
import { Inject, Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { HttpClientModule, HttpClientService } from '~/http-client/http-client.service';
import { UniqueConfigNamespaced } from '../config';
import { UploadFileForIngestionCommand } from './upload-file-for-ingestion.command';

const OUTLOOK_SEMANTIC_MCP_TOKEN_NAME = 'outlook-semantic-mcp';

export const InjectUniqueApi = () =>
  Inject(getUniqueApiClientToken(OUTLOOK_SEMANTIC_MCP_TOKEN_NAME));

const UNIQUE_API_FEATURE_MODULE = UniqueApiModule.forFeatureAsync(OUTLOOK_SEMANTIC_MCP_TOKEN_NAME, {
  imports: [ConfigModule],
  inject: [ConfigService],
  useFactory: (
    configService: ConfigService<UniqueConfigNamespaced, true>,
  ): UniqueApiFeatureModuleInputOptions => {
    const uniqueConfig = configService.get('unique', { infer: true });
    return {
      auth: uniqueConfig,
      ingestion: { baseUrl: uniqueConfig.ingestionServiceBaseUrl },
      scopeManagement: { baseUrl: uniqueConfig.scopeManagementServiceBaseUrl },
    };
  },
});

@Module({
  imports: [ConfigModule, UNIQUE_API_FEATURE_MODULE, HttpClientModule],
  providers: [
    {
      inject: [ConfigService, HttpClientService],
      provide: UploadFileForIngestionCommand,
      useFactory: (
        configService: ConfigService<UniqueConfigNamespaced, true>,
        service: HttpClientService,
      ): UploadFileForIngestionCommand => {
        return new UploadFileForIngestionCommand(
          configService.get('unique', { infer: true }),
          service,
        );
      },
    },
  ],
  exports: [UNIQUE_API_FEATURE_MODULE, UploadFileForIngestionCommand],
})
export class UniqueApiFeatureModule {}
