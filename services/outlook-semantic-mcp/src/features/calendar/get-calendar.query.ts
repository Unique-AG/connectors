import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GraphCalendarSchema } from './calendar.schemas';
import { calendarPath, defaultCalendarPath } from './utils/calendar-graph-path';
import {
  calendarLogUser,
  calendarTraceAttrs,
  calendarUserProfileId,
  recoverCalendarGraphError,
} from './utils/calendar-observability';
import type { CalendarRefInput } from './utils/calendar-ref.schema';

const CALENDAR_SELECT = 'id,name,owner,canEdit,isDefaultCalendar';

export interface CalendarSummary {
  calendarId: string;
  name: string;
  isDefaultCalendar: boolean;
  isOwn: boolean;
  ownerEmail: string | null;
  ownerName: string | null;
  canEdit: boolean;
}

export interface GetCalendarQueryInput {
  /** Omit to resolve the signed-in user default calendar. */
  calendarRef?: CalendarRefInput;
}

export interface GetCalendarQueryOutput {
  success: boolean;
  message: string;
  calendar?: CalendarSummary;
  consentRequired?: boolean;
}

/**
 * Resolves a calendarRef to the calendar it names, so a write can be confirmed against the real
 * calendar name and owner rather than an opaque id.
 */
@Injectable()
export class GetCalendarQuery {
  private readonly logger = new Logger(GetCalendarQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: GetCalendarQueryInput,
  ): Promise<GetCalendarQueryOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const path =
      input.calendarRef === undefined
        ? defaultCalendarPath()
        : calendarPath(input.calendarRef.calendarId);
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      userProfileEmail: userProfile.email,
      calendarId: input.calendarRef?.calendarId,
      operation: 'get_calendar',
    });
    const client = this.graphClientFactory.createClientForUser(userProfile.id);

    try {
      const raw = await client.api(path).select(CALENDAR_SELECT).get();
      const parsed = GraphCalendarSchema.parse(raw);
      const ownerEmail = parsed.owner?.address ?? null;
      this.logger.debug({
        ...calendarLogUser(userProfileIdString, userProfile.email),
        calendarId: parsed.id,
        msg: 'get_calendar',
      });
      return {
        success: true,
        message: 'Loaded the calendar.',
        calendar: {
          calendarId: parsed.id,
          name: parsed.name ?? '',
          isDefaultCalendar: parsed.isDefaultCalendar ?? false,
          isOwn:
            ownerEmail !== null && ownerEmail.toLowerCase() === userProfile.email.toLowerCase(),
          ownerEmail,
          ownerName: parsed.owner?.name ?? null,
          canEdit: parsed.canEdit ?? false,
        },
      };
    } catch (error) {
      return recoverCalendarGraphError({
        error,
        logger: this.logger,
        userProfileId: userProfileIdString,
        userProfileEmail: userProfile.email,
        calendarId: input.calendarRef?.calendarId,
        operation: 'get_calendar',
        notFoundMessage:
          'That calendar was not found. Call list_calendars again and pass calendarRef without changing it.',
      });
    }
  }
}
