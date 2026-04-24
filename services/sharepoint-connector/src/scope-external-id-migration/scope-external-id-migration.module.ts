import { Module } from '@nestjs/common';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ScopeExternalIdMigrationService } from './scope-external-id-migration.service';

@Module({
  imports: [UniqueApiModule],
  providers: [ScopeExternalIdMigrationService],
  exports: [ScopeExternalIdMigrationService],
})
export class ScopeExternalIdMigrationModule {}
