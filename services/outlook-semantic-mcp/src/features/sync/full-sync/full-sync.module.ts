import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DrizzleModule } from '~/db/drizzle.module';
import { InboxDeletingQueryModule } from '~/features/delete-inbox/inbox-deleting-query.module';
import { DirectoriesSyncModule } from '~/features/directories-sync/directories-sync.module';
import { MetricsModule } from '~/features/metrics/metrics.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { ProcessEmailModule } from '../../process-email/process-email.module';
import { UserUtilsModule } from '../../user-utils/user-utils.module';
import { FindInboxConfigByVersionQuery } from './find-inbox-config-by-version.query';
import { FullSyncCommand } from './full-sync.command';
import { FullSyncListener } from './full-sync.listener';
import { FullSyncResetCommand } from './full-sync-reset.command';
import { GetFullSyncStatsQuery } from './get-full-sync-stats.query';
import { GetScopeIngestionStatsQuery } from './get-scope-ingestion-stats.query';
import { PauseFullSyncCommand } from './pause-full-sync.command';
import { ProcessFullSyncBatchCommand } from './process-full-sync-batch.command';
import { ResumeFullSyncCommand } from './resume-full-sync.command';
import { UpdateInboxConfigByVersionCommand } from './update-inbox-config-by-version.command';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    UserUtilsModule,
    UniqueApiFeatureModule,
    ProcessEmailModule,
    DirectoriesSyncModule,
    InboxDeletingQueryModule,
    ConfigModule,
    MetricsModule,
  ],
  providers: [
    FullSyncCommand,
    FullSyncResetCommand,
    PauseFullSyncCommand,
    ResumeFullSyncCommand,
    FullSyncListener,
    GetFullSyncStatsQuery,
    GetScopeIngestionStatsQuery,
    UpdateInboxConfigByVersionCommand,
    FindInboxConfigByVersionQuery,
    ProcessFullSyncBatchCommand,
  ],
  exports: [
    FullSyncCommand,
    FullSyncResetCommand,
    PauseFullSyncCommand,
    ResumeFullSyncCommand,
    GetFullSyncStatsQuery,
    GetScopeIngestionStatsQuery,
    UpdateInboxConfigByVersionCommand,
    FindInboxConfigByVersionQuery,
  ],
})
export class FullSyncModule {}
