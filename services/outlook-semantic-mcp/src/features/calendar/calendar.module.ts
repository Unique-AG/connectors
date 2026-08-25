import { Module } from '@nestjs/common';
import { DelegatedAccessUtilsModule } from '~/features/delegated-access/delegated-access-utils.module';
import { MetricsModule } from '~/features/metrics/metrics.module';
import { UserUtilsModule } from '~/features/user-utils/user-utils.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { CheckAvailabilityQuery } from './check-availability.query';
import { ListCalendarsQuery } from './list-calendars.query';
import { RespondToInviteCommand } from './respond-to-invite.command';
import { SearchCalendarEventsQuery } from './search-calendar-events.query';
import { SuggestMeetingTimesQuery } from './suggest-meeting-times.query';

const QUERIES = [
  ListCalendarsQuery,
  SearchCalendarEventsQuery,
  CheckAvailabilityQuery,
  SuggestMeetingTimesQuery,
];
const COMMANDS = [RespondToInviteCommand];

@Module({
  imports: [MsGraphModule, UserUtilsModule, DelegatedAccessUtilsModule, MetricsModule],
  providers: [...QUERIES, ...COMMANDS],
  exports: [...QUERIES, ...COMMANDS],
})
export class CalendarModule {}
