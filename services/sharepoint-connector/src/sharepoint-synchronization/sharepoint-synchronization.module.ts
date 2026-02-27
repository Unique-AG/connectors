import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MetricsModule } from '../metrics/metrics.module';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { PermissionsSyncModule } from '../permissions-sync/permissions-sync.module';
import { ProcessingPipelineModule } from '../processing-pipeline/processing-pipeline.module';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ContentSyncService } from './content-sync.service';
import { FileMoveProcessor } from './file-move-processor.service';
import { RootScopeMigrationService } from './root-scope-migration.service';
import { ScopeManagementService } from './scope-management.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';
import { SubsiteDiscoveryService } from './subsite-discovery.service';

@Module({
  imports: [
    ConfigModule,
    MetricsModule,
    MicrosoftApisModule,
    UniqueApiModule,
    ProcessingPipelineModule,
    PermissionsSyncModule,
  ],
  providers: [
    SharepointSynchronizationService,
    ContentSyncService,
    FileMoveProcessor,
    RootScopeMigrationService,
    ScopeManagementService,
    SubsiteDiscoveryService,
  ],
  exports: [SharepointSynchronizationService],
})
export class SharepointSynchronizationModule {}
