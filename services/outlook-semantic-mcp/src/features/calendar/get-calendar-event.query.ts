import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { type EventRef, GraphEventSnapshotSchema } from './calendar.schemas';
import { eventPath } from './utils/calendar-graph-path';
import {
  calendarLogUser,
  calendarTraceAttrs,
  calendarUserProfileId,
  recoverCalendarGraphError,
} from './utils/calendar-observability';
import { type CalendarDateTime, mapGraphDateTime } from './utils/map-graph-date-time';
import { type GraphEventType, parseGraphEventType } from './utils/resolve-write-event-id';

const EVENT_SELECT =
  'id,subject,start,end,location,attendees,organizer,isCancelled,type,seriesMasterId';

export interface CalendarEventSnapshot {
  eventId: string;
  calendarId: string;
  type: GraphEventType;
  seriesMasterId: string | null;
  subject: string | null;
  start: CalendarDateTime | null;
  end: CalendarDateTime | null;
  location: string | null;
  organizerName: string | null;
  organizerEmail: string | null;
  isCancelled: boolean;
  attendeeCount: number;
}

export interface GetCalendarEventQueryInput {
  eventRef: EventRef;
}

export interface GetCalendarEventQueryOutput {
  success: boolean;
  message: string;
  event?: CalendarEventSnapshot;
  consentRequired?: boolean;
}

@Injectable()
export class GetCalendarEventQuery {
  private readonly logger = new Logger(GetCalendarEventQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly resolveMailboxTimezoneQuery: ResolveMailboxTimezoneQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: GetCalendarEventQueryInput,
  ): Promise<GetCalendarEventQueryOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    assert.ok(input.eventRef.eventId.length > 0, 'eventRef.eventId must already be set');
    assert.ok(input.eventRef.calendarId.length > 0, 'eventRef.calendarId must already be set');

    this.logger.debug({
      userProfileId: userProfileIdString,
      calendarId: input.eventRef.calendarId,
      msg: 'get_calendar_event started',
    });

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      userProfileEmail: userProfile.email,
      calendarId: input.eventRef.calendarId,
      operation: 'get_calendar_event',
    });
    const { outlookTimeZone } = await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const path = eventPath({
      calendarId: input.eventRef.calendarId,
      eventId: input.eventRef.eventId,
    });

    try {
      const raw = await client
        .api(path)
        .header('Prefer', `outlook.timezone="${outlookTimeZone}", IdType="ImmutableId"`)
        .select(EVENT_SELECT)
        .get();
      const parsed = GraphEventSnapshotSchema.parse(raw);
      this.logger.debug({
        ...calendarLogUser(userProfileIdString, userProfile.email),
        calendarId: input.eventRef.calendarId,
        type: parsed.type,
        msg: 'get_calendar_event',
      });
      return {
        success: true,
        message: 'Loaded the event.',
        event: {
          eventId: parsed.id,
          calendarId: input.eventRef.calendarId,
          type: parseGraphEventType(parsed.type),
          seriesMasterId:
            parsed.seriesMasterId !== undefined &&
            parsed.seriesMasterId !== null &&
            parsed.seriesMasterId.length > 0
              ? parsed.seriesMasterId
              : null,
          subject: parsed.subject ?? null,
          start: mapGraphDateTime(parsed.start),
          end: mapGraphDateTime(parsed.end),
          location: parsed.location?.displayName ?? null,
          organizerName: parsed.organizer?.emailAddress?.name ?? null,
          organizerEmail: parsed.organizer?.emailAddress?.address ?? null,
          isCancelled: parsed.isCancelled ?? false,
          attendeeCount: parsed.attendees?.length ?? 0,
        },
      };
    } catch (error) {
      return recoverCalendarGraphError({
        error,
        logger: this.logger,
        userProfileId: userProfileIdString,
        userProfileEmail: userProfile.email,
        calendarId: input.eventRef.calendarId,
        operation: 'get_calendar_event',
        notFoundMessage:
          'That event was not found. Search again and pass eventRef without changing it.',
      });
    }
  }
}
