import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  type CalendarMetricErrorType,
  CalendarMetricsService,
} from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import { CalendarRef, GraphCalendarCollectionSchema } from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
} from './utils/calendar-graph-errors';
import { calendarCollectionPath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  logCalendarRecovered,
} from './utils/calendar-observability';
import { mapGraphCalendarToCalendarRef } from './utils/map-graph-calendar-to-calendar-ref';

const CALENDAR_SELECT =
  'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar,isTallyingResponses';

export interface ListCalendarsQueryOutput {
  success: boolean;
  message: string;
  calendars?: CalendarRef[];
  consentRequired?: boolean;
  errorType?: CalendarMetricErrorType;
}

@Injectable()
export class ListCalendarsQuery {
  private readonly logger = new Logger(ListCalendarsQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<ListCalendarsQueryOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({ userProfileId: userProfileIdString, msg: 'list_calendars started' });
    calendarTraceAttrs({ userProfileId: userProfileIdString, operation: 'list_calendars' });
    return this.calendarMetrics.measureOperation({ operation: 'list_calendars' }, async () => {
      const userProfile = await this.getUserProfileQuery.run(userProfileId);
      const client = this.graphClientFactory.createClientForUser(userProfile.id);

      try {
        const calendars = rankCalendars(
          await this.fetchCalendars({
            client,
            path: calendarCollectionPath(userProfile.email),
            mailboxEmail: userProfile.email,
            callerEmail: userProfile.email,
            userProfileId: userProfileIdString,
          }),
        );
        this.logger.log({
          userProfileId: userProfileIdString,
          mailbox: obfuscateEmail(userProfile.email),
          calendarCount: calendars.length,
          msg: 'list_calendars',
        });
        return {
          success: true,
          message:
            calendars.length === 0
              ? 'No calendars were returned.'
              : `Found ${calendars.length} calendar${calendars.length === 1 ? '' : 's'}.`,
          calendars,
        };
      } catch (error) {
        if (error instanceof CalendarConsentRequiredError) {
          logCalendarRecovered(this.logger, {
            userProfileId: userProfileIdString,
            mailbox: userProfile.email,
            outcome: 'consent',
            msg: 'list_calendars consent required',
            err: error,
          });
          return {
            success: false,
            message: error.message,
            consentRequired: true,
            errorType: 'consent' as const,
          };
        }
        throw error;
      }
    });
  }

  @Span()
  private async fetchCalendars(input: {
    client: Client;
    path: string;
    mailboxEmail: string;
    callerEmail: string;
    userProfileId: string;
  }): Promise<CalendarRef[]> {
    calendarTraceAttrs({
      userProfileId: input.userProfileId,
      mailbox: input.mailboxEmail,
      operation: 'list_calendars.fetch',
    });
    const calendars: CalendarRef[] = [];
    let nextPath: string | undefined = input.path;
    let isFirst = true;

    while (nextPath) {
      try {
        const request = input.client.api(nextPath);
        const raw = isFirst
          ? await request.select(CALENDAR_SELECT).top(100).get()
          : await request.get();
        isFirst = false;
        const parsed = GraphCalendarCollectionSchema.parse(raw);
        for (const item of parsed.value) {
          calendars.push(
            mapGraphCalendarToCalendarRef({
              calendar: item,
              callerEmail: input.callerEmail,
              mailboxEmail: input.mailboxEmail,
            }),
          );
        }
        nextPath = parsed['@odata.nextLink'];
      } catch (error) {
        if (isCalendarPermissionDeniedError(error)) {
          throw new CalendarConsentRequiredError();
        }
        throw error;
      }
    }

    return calendars;
  }
}

/** Primary calendars first so holiday and extra calendars do not hide the meeting calendars. */
function rankCalendars(calendars: CalendarRef[]): CalendarRef[] {
  return [...calendars].sort((left, right) => calendarRank(left) - calendarRank(right));
}

function calendarRank(calendar: CalendarRef): number {
  if (calendar.isDefaultCalendar) {
    return calendar.isOwn ? 0 : 1;
  }
  return calendar.isOwn ? 2 : 3;
}
