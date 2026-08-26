import { Module } from '@nestjs/common';
import { MetricsModule } from '~/features/metrics/metrics.module';
import { UserUtilsModule } from '~/features/user-utils/user-utils.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { CancelEventCommand } from './cancel-event.command';
import { CheckAvailabilityQuery } from './check-availability.query';
import { CreateEventCommand } from './create-event.command';
import { GetCalendarQuery } from './get-calendar.query';
import { GetCalendarEventQuery } from './get-calendar-event.query';
import { ListCalendarsQuery } from './list-calendars.query';
import { RespondToInviteCommand } from './respond-to-invite.command';
import { SearchCalendarEventsQuery } from './search-calendar-events.query';
import { SuggestMeetingTimesQuery } from './suggest-meeting-times.query';
import { UpdateEventCommand } from './update-event.command';

const QUERIES = [
  ListCalendarsQuery,
  SearchCalendarEventsQuery,
  CheckAvailabilityQuery,
  SuggestMeetingTimesQuery,
  GetCalendarEventQuery,
  GetCalendarQuery,
];
const COMMANDS = [
  RespondToInviteCommand,
  CreateEventCommand,
  UpdateEventCommand,
  CancelEventCommand,
];

@Module({
  imports: [MsGraphModule, UserUtilsModule, MetricsModule],
  providers: [...QUERIES, ...COMMANDS],
  exports: [...QUERIES, ...COMMANDS],
})
export class CalendarModule {}
