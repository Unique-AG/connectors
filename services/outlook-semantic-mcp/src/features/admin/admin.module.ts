import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { SearchModule } from '~/features/content';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { FetchMessagesFromGraphQuery } from './fetch-messages-from-graph.query';
import { RunSearchRecallCheckQuery } from './run-search-recall-check.query';
import { RunSyncDiagnosticsQuery } from './run-sync-diagnostics.query';

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueApiFeatureModule, SearchModule],
  providers: [FetchMessagesFromGraphQuery, RunSyncDiagnosticsQuery, RunSearchRecallCheckQuery],
  exports: [FetchMessagesFromGraphQuery, RunSyncDiagnosticsQuery, RunSearchRecallCheckQuery],
})
export class AdminModule {}
