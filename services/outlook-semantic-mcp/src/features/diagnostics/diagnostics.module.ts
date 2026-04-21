import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { RunSyncDiagnosticsQuery } from './run-sync-diagnostics.query';

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueApiFeatureModule],
  providers: [RunSyncDiagnosticsQuery],
  exports: [RunSyncDiagnosticsQuery],
})
export class DiagnosticsModule {}
