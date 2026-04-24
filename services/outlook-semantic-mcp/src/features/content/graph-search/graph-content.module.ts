import { Module } from '@nestjs/common';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { GraphOpenEmailQuery } from './graph-open-email.query';
import { GraphSearchEmailsQuery } from './graph-search-emails.query';

@Module({
  imports: [MsGraphModule],
  providers: [GraphSearchEmailsQuery, GraphOpenEmailQuery],
  exports: [GraphSearchEmailsQuery, GraphOpenEmailQuery],
})
export class GraphContentModule {}
