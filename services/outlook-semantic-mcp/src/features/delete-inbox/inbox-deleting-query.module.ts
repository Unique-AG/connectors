import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { IsInboxDeletingQuery } from './is-inbox-deleting.query';

@Module({
  imports: [DrizzleModule],
  providers: [IsInboxDeletingQuery],
  exports: [IsInboxDeletingQuery],
})
export class InboxDeletingQueryModule {}
