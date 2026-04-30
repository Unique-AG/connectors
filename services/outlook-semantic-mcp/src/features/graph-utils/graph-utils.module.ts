import { Module } from '@nestjs/common';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { TranslateGraphIdsToImmutableIdsQuery } from './translate-graph-ids-to-immutable-ids.query';

@Module({
  imports: [MsGraphModule],
  providers: [TranslateGraphIdsToImmutableIdsQuery],
  exports: [TranslateGraphIdsToImmutableIdsQuery],
})
export class GraphUtilsModule {}
