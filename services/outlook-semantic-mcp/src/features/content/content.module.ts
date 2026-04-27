import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { FullSyncModule } from '../sync/full-sync';
import { SemanticSearchEmailsQuery } from './search/semantic-search-emails.query';

const QUERIES = [SemanticSearchEmailsQuery];

@Module({
  imports: [DrizzleModule, UniqueApiFeatureModule, FullSyncModule],
  providers: [...QUERIES],
  exports: [...QUERIES],
})
export class ContentModule {}
