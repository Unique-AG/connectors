import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DelegatedAccessUtilsModule } from '../delegated-access/delegated-access-utils.module';
import { GraphUtilsModule } from '../graph-utils/graph-utils.module';
import { FullSyncModule } from '../sync/full-sync';
import { UserUtilsModule } from '../user-utils/user-utils.module';
import { BuildMsGraphKqlBatchRequestsQuery } from './search/build-ms-graph-kql-batch-requests.query';
import { CleanupSearchConditionsForUserQuery } from './search/cleanup-search-conditions-for-user.query';
import { MsGraphKqlSearchEmailsQuery } from './search/ms-graph-kql-search-emails.query';
import { SearchEmailsQuery } from './search/search-emails.query';
import { SemanticSearchEmailsQuery } from './search/semantic-search-emails.query';

const QUERIES = [
  SemanticSearchEmailsQuery,
  MsGraphKqlSearchEmailsQuery,
  SearchEmailsQuery,
  CleanupSearchConditionsForUserQuery,
  BuildMsGraphKqlBatchRequestsQuery,
];

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    UniqueApiFeatureModule,
    FullSyncModule,
    GraphUtilsModule,
    UserUtilsModule,
    DelegatedAccessUtilsModule,
  ],
  providers: [...QUERIES],
  exports: [...QUERIES],
})
export class ContentModule {}
