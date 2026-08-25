import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import type { EventRef } from './calendar.schemas';
import { eventPath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  classifyCalendarGraphError,
  logCalendarRecovered,
} from './utils/calendar-observability';
import { type GraphEventType, parseGraphEventType } from './utils/resolve-write-event-id';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

const EVENT_SELECT = 'id,subject,start,end,location,attendees,isCancelled,type,seriesMasterId';

const SnapshotSchema = z.object({
  id: z.string(),
  subject: z.string().optional().nullable(),
  start: z.object({ dateTime: z.string().optional(), timeZone: z.string().optional() }).nullish(),
  end: z.object({ dateTime: z.string().optional(), timeZone: z.string().optional() }).nullish(),
  location: z.object({ displayName: z.string().optional() }).nullish(),
  attendees: z.array(z.unknown()).nullish(),
  isCancelled: z.boolean().nullish(),
  type: z.string().nullish(),
  seriesMasterId: z.string().nullish(),
});

export interface CalendarEventSnapshot {
  eventId: string;
  calendarId: string;
  mailbox: string;
  type: GraphEventType;
  seriesMasterId: string | null;
  subject: string | null;
  start: { dateTime: string; timeZone: string | null } | null;
  end: { dateTime: string; timeZone: string | null } | null;
  location: string | null;
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
    assert.ok(
      SmtpAddressSchema.safeParse(input.eventRef.mailbox).success,
      'eventRef.mailbox must already be an SMTP address',
    );
    assert.ok(input.eventRef.eventId.length > 0, 'eventRef.eventId must already be set');
    assert.ok(input.eventRef.calendarId.length > 0, 'eventRef.calendarId must already be set');

    const mailbox = input.eventRef.mailbox;
    this.logger.debug({
      userProfileId: userProfileIdString,
      mailbox: obfuscateEmail(mailbox),
      calendarId: input.eventRef.calendarId,
      msg: 'get_calendar_event started',
    });
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox,
      calendarId: input.eventRef.calendarId,
      operation: 'get_calendar_event',
    });

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const { outlookTimeZone } = await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const path = eventPath({
      mailboxEmail: mailbox,
      calendarId: input.eventRef.calendarId,
      eventId: input.eventRef.eventId,
    });

    try {
      const raw = await client
        .api(path)
        .header('Prefer', `outlook.timezone="${outlookTimeZone}", IdType="ImmutableId"`)
        .select(EVENT_SELECT)
        .get();
      const parsed = SnapshotSchema.parse(raw);
      this.logger.debug({
        userProfileId: userProfileIdString,
        mailbox: obfuscateEmail(mailbox),
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
          mailbox,
          type: parseGraphEventType(parsed.type),
          seriesMasterId:
            parsed.seriesMasterId !== undefined &&
            parsed.seriesMasterId !== null &&
            parsed.seriesMasterId.length > 0
              ? parsed.seriesMasterId
              : null,
          subject: parsed.subject ?? null,
          start: dateTime(parsed.start),
          end: dateTime(parsed.end),
          location: parsed.location?.displayName ?? null,
          isCancelled: parsed.isCancelled ?? false,
          attendeeCount: parsed.attendees?.length ?? 0,
        },
      };
    } catch (error) {
      const recovered = classifyCalendarGraphError({
        error,
        mailbox,
        callerEmail: userProfile.email,
        notFoundMessage:
          'That event was not found. Search again and pass eventRef without changing it.',
        deniedDelegatedMessage: `Could not read an event on mailbox ${mailbox}.`,
      });
      if (recovered === undefined) {
        throw error;
      }
      logCalendarRecovered(this.logger, {
        userProfileId: userProfileIdString,
        mailbox,
        calendarId: input.eventRef.calendarId,
        outcome: recovered.outcome,
        msg: `get_calendar_event ${recovered.outcome}`,
        err: error,
      });
      return {
        success: false,
        message: recovered.message,
        ...(recovered.consentRequired === true ? { consentRequired: true } : {}),
      };
    }
  }
}

function dateTime(
  value: { dateTime?: string; timeZone?: string } | null | undefined,
): { dateTime: string; timeZone: string | null } | null {
  if (value?.dateTime === undefined || value.dateTime === '') {
    return null;
  }
  return { dateTime: value.dateTime, timeZone: value.timeZone ?? null };
}
