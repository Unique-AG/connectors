import { Module } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import {
  type FetchFn,
  pipeline,
  withBaseUrl,
  withHeaders,
  withResponseError,
} from '@qfetch/qfetch';
import type { UniqueConfigNamespaced } from '~/config';
import { DrizzleModule } from '../drizzle/drizzle.module';
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
      inject: [ConfigService],
      useFactory(config: ConfigService<UniqueConfigNamespaced, true>): FetchFn {
        const uniqueConfig = config.get('unique', { infer: true });
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
