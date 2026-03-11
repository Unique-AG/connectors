import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { FullSyncModule } from '../full-sync';
import { SearchEmailsQuery } from './search/search-emails.query';

const QUERIES = [SearchEmailsQuery];

@Module({
  imports: [DrizzleModule, UniqueApiFeatureModule, FullSyncModule],
  providers: [...QUERIES],
  exports: [...QUERIES],
})
export class ContentModule {}
