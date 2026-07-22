import { Module } from '@nestjs/common';
import {
  type FetchFn,
  pipeline,
  withBaseUrl,
  withHeaders,
  withResponseError,
} from '@qfetch/qfetch';
import type { EnabledUniqueConfig } from '~/config';
import { KB_INTEGRATION_ENABLED_CONFIG } from '~/kb-integration/kb-integration-config.module';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { RootScopeBootstrapService } from './root-scope-bootstrap.service';
import { UNIQUE_FETCH } from './unique.consts';
import { UniqueService } from './unique.service';
import { UniqueContentService } from './unique-content.service';
import { UniqueScopeService } from './unique-scope.service';
import { UniqueUserService } from './unique-user.service';
import { UniqueUserMappingService } from './unique-user-mapping.service';

@Module({
  imports: [DrizzleModule],
  providers: [
    {
      provide: UNIQUE_FETCH,
      inject: [KB_INTEGRATION_ENABLED_CONFIG],
      useFactory(uniqueConfig: EnabledUniqueConfig): FetchFn {
        return pipeline(
          withBaseUrl(uniqueConfig.apiBaseUrl),
          withHeaders({
            'x-api-version': uniqueConfig.apiVersion,
            ...uniqueConfig.serviceExtraHeaders,
          }),
          withResponseError(),
        )(fetch);
      },
    },
    UniqueUserService,
    UniqueUserMappingService,
    UniqueScopeService,
    UniqueContentService,
    UniqueService,
    RootScopeBootstrapService,
  ],
  exports: [
    UNIQUE_FETCH,
    UniqueService,
    UniqueContentService,
    UniqueUserService,
    UniqueUserMappingService,
    UniqueScopeService,
  ],
})
export class UniqueModule {}
