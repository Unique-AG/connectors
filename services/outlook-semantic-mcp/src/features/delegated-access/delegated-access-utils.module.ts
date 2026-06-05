import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DrizzleModule } from '~/db/drizzle.module';
import { RemoveDelegatedAccessCommand } from './commands/remove-delegated-access.command';
import { GetDelegatedAccessQuery } from './queries/get-delegates-access.query';
import { GetDirectoryDelegatedAccessQuery } from './queries/get-directory-delegated-access.query';
import { GetFullDelegatedAccessQuery } from './queries/get-full-delegated-access.query';
import { ListMailboxesAndDirectoriesQuery } from './queries/list-mailboxes-and-directories.query';

@Module({
  imports: [DrizzleModule, ConfigModule],
  providers: [
    GetFullDelegatedAccessQuery,
    GetDirectoryDelegatedAccessQuery,
    GetDelegatedAccessQuery,
    RemoveDelegatedAccessCommand,
    ListMailboxesAndDirectoriesQuery,
  ],
  exports: [
    GetFullDelegatedAccessQuery,
    GetDelegatedAccessQuery,
    RemoveDelegatedAccessCommand,
    ListMailboxesAndDirectoriesQuery,
  ],
})
export class DelegatedAccessUtilsModule {}
