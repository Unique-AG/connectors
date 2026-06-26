import { Module } from '@nestjs/common';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { BuildWebLinksCommand } from './build-web-links.command';
import { TranslateGraphIdsToImmutableIdsQuery } from './translate-graph-ids-to-immutable-ids.query';
import { TranslateImmutableIdsToRestIdsQuery } from './translate-immutable-ids-to-rest-ids.query';

@Module({
  imports: [MsGraphModule],
  providers: [
    TranslateGraphIdsToImmutableIdsQuery,
    TranslateImmutableIdsToRestIdsQuery,
    BuildWebLinksCommand,
  ],
  exports: [
    TranslateGraphIdsToImmutableIdsQuery,
    TranslateImmutableIdsToRestIdsQuery,
    BuildWebLinksCommand,
  ],
})
export class GraphUtilsModule {}
