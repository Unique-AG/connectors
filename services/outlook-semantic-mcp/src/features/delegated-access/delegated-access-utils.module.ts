import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DrizzleModule } from '~/db/drizzle.module';
import { RemoveDelegatedAccessCommand } from './commands/remove-delegated-access.command';
import { GetDelegatedAccessQuery } from './queries/get-delegates-access.query';
import { GetDirectoryDelegatedAccessQuery } from './queries/get-directory-delegated-access.query';
import { GetFullDelegatedAccessQuery } from './queries/get-full-delegated-access.query';
import { GetMailboxesWithFullDelegatedAccessQuery } from './queries/get-mailboxes-with-full-delegated-access.query';

@Module({
  imports: [DrizzleModule, ConfigModule],
  providers: [
    GetFullDelegatedAccessQuery,
    GetDirectoryDelegatedAccessQuery,
    GetDelegatedAccessQuery,
    GetMailboxesWithFullDelegatedAccessQuery,
    RemoveDelegatedAccessCommand,
  ],
  exports: [
    GetFullDelegatedAccessQuery,
    GetDelegatedAccessQuery,
    GetMailboxesWithFullDelegatedAccessQuery,
    RemoveDelegatedAccessCommand,
  ],
})
export class DelegatedAccessUtilsModule {}
