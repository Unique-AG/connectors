import {
  ClusterLocalAuthConfig,
  ExternalAuthConfig,
  getUniqueApiClientToken,
  UniqueApiClientConfig,
  UniqueApiModule,
} from '@unique-ag/unique-api';
import { Inject } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { UniqueConfig, uniqueConfig } from '../config';

const OUTLOOK_SEMANTIC_MCP_TOKEN_NAME = 'outlook-semantic-mcp';

export const InjectUniqueApi = () =>
  Inject(getUniqueApiClientToken(OUTLOOK_SEMANTIC_MCP_TOKEN_NAME));

export const UNIQUE_API_FEATURE_MODULE = UniqueApiModule.forFeatureAsync(
  OUTLOOK_SEMANTIC_MCP_TOKEN_NAME,
  {
    imports: [ConfigModule],
    inject: [uniqueConfig.KEY],
    useFactory: (config: UniqueConfig): UniqueApiClientConfig => {
      // console.log(`--------------------${JSON.stringify(config, null, 4)}`);

      let auth: ClusterLocalAuthConfig | ExternalAuthConfig;
      if (config.serviceAuthMode === 'external') {
        auth = {
          mode: 'external',
          zitadelOauthTokenUrl: config.zitadelOauthTokenUrl,
          zitadelClientId: config.zitadelClientId,
          zitadelClientSecret: config.zitadelClientSecret,
          zitadelProjectId: config.zitadelProjectId,
        };
      } else {
        auth = {
          mode: 'cluster_local',
          extraHeaders: config.serviceExtraHeaders,
          serviceId: `TEST`,
        };
      }

      return {
        auth,
        endpoints: {
          scopeManagementBaseUrl: config.scopeManagementServiceBaseUrl,
          ingestionBaseUrl: config.ingestionServiceBaseUrl,
        },
      };
    },
  },
);
