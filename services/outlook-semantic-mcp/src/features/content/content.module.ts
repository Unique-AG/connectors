import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { FullSyncModule } from '../sync/full-sync';
import { MsGraphKqlSearchEmailsQuery } from './search/ms-graph-kql-search-emails.query';
import { SearchEmailsQuery } from './search/search-emails.query';
import { SemanticSearchEmailsQuery } from './search/semantic-search-emails.query';

const QUERIES = [SemanticSearchEmailsQuery, MsGraphKqlSearchEmailsQuery, SearchEmailsQuery];

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueApiFeatureModule, FullSyncModule],
  providers: [...QUERIES],
  exports: [...QUERIES],
})
export class ContentModule {}
