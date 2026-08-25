import { Module } from '@nestjs/common';
import { DelegatedAccessUtilsModule } from '~/features/delegated-access/delegated-access-utils.module';
import { UserUtilsModule } from '~/features/user-utils/user-utils.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { ListCalendarsQuery } from './list-calendars.query';

const QUERIES = [ListCalendarsQuery];

@Module({
  imports: [MsGraphModule, UserUtilsModule, DelegatedAccessUtilsModule],
  providers: [...QUERIES],
  exports: [...QUERIES],
})
export class CalendarModule {}
