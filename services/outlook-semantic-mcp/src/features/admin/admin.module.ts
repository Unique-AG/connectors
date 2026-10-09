import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { SearchModule } from '~/features/content';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DelegatedAccessUtilsModule } from '../delegated-access/delegated-access-utils.module';
import { GraphUtilsModule } from '../graph-utils/graph-utils.module';
import { UserUtilsModule } from '../user-utils/user-utils.module';
import { FetchMessagesFromGraphQuery } from './fetch-messages-from-graph.query';
import { ProbeSearchPagingQuery } from './probe-search-paging.query';
import { RunSearchRecallCheckQuery } from './run-search-recall-check.query';
import { RunSyncDiagnosticsQuery } from './run-sync-diagnostics.query';

const QUERIES = [
  FetchMessagesFromGraphQuery,
  RunSyncDiagnosticsQuery,
  RunSearchRecallCheckQuery,
  ProbeSearchPagingQuery,
];

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    UniqueApiFeatureModule,
    SearchModule,
    GraphUtilsModule,
    UserUtilsModule,
    DelegatedAccessUtilsModule,
  ],
  providers: [...QUERIES],
  exports: [...QUERIES],
})
export class AdminModule {}
