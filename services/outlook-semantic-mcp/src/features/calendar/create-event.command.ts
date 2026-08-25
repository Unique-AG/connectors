import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';
import {
  type CalendarMetricErrorType,
  CalendarMetricsService,
} from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import type { CalendarAccessPath, EventRef } from './calendar.schemas';
import { createEventPath, defaultCalendarPath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  classifyCalendarGraphError,
  logCalendarRecovered,
} from './utils/calendar-observability';
import { mapIsoToGraphDateTimeTimeZone } from './utils/map-iso-to-graph-date-time-time-zone';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

const MAX_ATTENDEES = 20;
const TRANSACTION_ID_MAX = 32;

const DefaultCalendarSchema = z.object({
  id: z.string().min(1),
});

const CreatedEventSchema = z.object({
  id: z.string(),
  subject: z.string().optional().nullable(),
  start: z.object({ dateTime: z.string().optional(), timeZone: z.string().optional() }).nullish(),
  end: z.object({ dateTime: z.string().optional(), timeZone: z.string().optional() }).nullish(),
  webLink: z.string().nullish(),
  onlineMeeting: z.object({ joinUrl: z.string().optional() }).nullish(),
  onlineMeetingUrl: z.string().nullish(),
  location: z.object({ displayName: z.string().optional() }).nullish(),
});

export interface CreateEventCommandInput {
  subject: string;
  startDateTime: string;
  endDateTime: string;
  attendees?: string[];
  location?: string;
  body?: string;
  isOnlineMeeting?: boolean;
  mailbox?: string;
  calendarId?: string;
  transactionId?: string;
}

export interface CreateEventCommandOutput {
  success: boolean;
  message: string;
  eventRef?: EventRef;
  subject?: string | null;
  start?: { dateTime: string; timeZone: string | null };
  end?: { dateTime: string; timeZone: string | null };
  location?: string | null;
  joinUrl?: string | null;
  webLink?: string | null;
  transactionId?: string;
  consentRequired?: boolean;
}

@Injectable()
export class CreateEventCommand {
  private readonly logger = new Logger(CreateEventCommand.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly resolveMailboxTimezoneQuery: ResolveMailboxTimezoneQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: CreateEventCommandInput,
  ): Promise<CreateEventCommandOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({
      userProfileId: userProfileIdString,
      mailbox: input.mailbox,
      calendarId: input.calendarId,
      attendeeCount: input.attendees?.length ?? 0,
      msg: 'create_event started',
    });
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox: input.mailbox,
      calendarId: input.calendarId,
      operation: 'create_event',
    });
    return this.calendarMetrics.measureOperation({ operation: 'create_event' }, (fail) =>
      this.create(userProfileId, userProfileIdString, input, fail),
    );
  }

  private async create(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
    input: CreateEventCommandInput,
    fail: (errorType: CalendarMetricErrorType) => void,
  ): Promise<CreateEventCommandOutput> {
    assert.ok(input.subject.trim() !== '', 'subject must already be set');
    const start = Temporal.Instant.from(input.startDateTime);
    const end = Temporal.Instant.from(input.endDateTime);
    assert.ok(
      Temporal.Instant.compare(end, start) > 0,
      'endDateTime must already be after startDateTime',
    );
    const attendees = uniqueAttendees(input.attendees ?? []);
    assert.ok(
      attendees.length <= MAX_ATTENDEES,
      'attendees must already be at most 20 SMTP addresses',
    );
    const transactionId = input.transactionId ?? newTransactionId();
    assert.ok(
      transactionId.length > 0 && transactionId.length <= TRANSACTION_ID_MAX,
      'transactionId must already be 1 to 32 characters',
    );

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const mailbox = input.mailbox ?? userProfile.email;
    assert.ok(
      SmtpAddressSchema.safeParse(mailbox).success,
      'mailbox must already be an SMTP address',
    );
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox,
      calendarId: input.calendarId,
      operation: 'create_event',
    });
    const { ianaTimeZone, outlookTimeZone } =
      await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const client = this.graphClientFactory.createClientForUser(userProfile.id);

    try {
      const calendarId =
        input.calendarId ??
        (await this.resolveDefaultCalendarId(client, mailbox, userProfileIdString));
      const path = createEventPath({ mailboxEmail: mailbox, calendarId });
      const startTime = mapIsoToGraphDateTimeTimeZone({
        iso: input.startDateTime,
        ianaTimeZone,
        windowsTimeZone: outlookTimeZone,
      });
      const endTime = mapIsoToGraphDateTimeTimeZone({
        iso: input.endDateTime,
        ianaTimeZone,
        windowsTimeZone: outlookTimeZone,
      });
      const raw = await client
        .api(path)
        .header('Prefer', `outlook.timezone="${outlookTimeZone}", IdType="ImmutableId"`)
        .post({
          subject: input.subject.trim(),
          start: startTime,
          end: endTime,
          transactionId,
          ...(input.body !== undefined && input.body.trim() !== ''
            ? { body: { contentType: 'text', content: input.body } }
            : {}),
          ...(input.location !== undefined && input.location.trim() !== ''
            ? { location: { displayName: input.location.trim() } }
            : {}),
          ...(attendees.length > 0
            ? {
                attendees: attendees.map((address) => ({
                  type: 'required',
                  emailAddress: { address },
                })),
              }
            : {}),
          ...(input.isOnlineMeeting === true
            ? { isOnlineMeeting: true, onlineMeetingProvider: 'teamsForBusiness' }
            : {}),
        });
      const created = CreatedEventSchema.parse(raw);
      this.logger.log({
        userProfileId: userProfileIdString,
        mailbox,
        calendarId,
        transactionId,
        attendeeCount: attendees.length,
        msg: 'create_event',
      });
      return {
        success: true,
        message:
          attendees.length > 0
            ? 'Created the event and sent invitations immediately.'
            : 'Created the event.',
        eventRef: {
          eventId: created.id,
          calendarId,
          accessPath: accessPathForMailbox(mailbox, userProfile.email),
          mailbox,
        },
        subject: created.subject ?? input.subject.trim(),
        start: {
          dateTime: created.start?.dateTime ?? startTime.dateTime,
          timeZone: created.start?.timeZone ?? startTime.timeZone,
        },
        end: {
          dateTime: created.end?.dateTime ?? endTime.dateTime,
          timeZone: created.end?.timeZone ?? endTime.timeZone,
        },
        location: created.location?.displayName ?? input.location?.trim() ?? null,
        joinUrl: created.onlineMeeting?.joinUrl ?? created.onlineMeetingUrl ?? null,
        webLink: created.webLink ?? null,
        transactionId,
      };
    } catch (error) {
      const recovered = classifyCalendarGraphError({
        error,
        mailbox,
        callerEmail: userProfile.email,
        notFoundMessage:
          'That calendar was not found. List calendars again and pass calendarId without changing it.',
        invalidMessage: 'Graph rejected the event. Check the start and end times and try again.',
        deniedDelegatedMessage: `Could not create an event on mailbox ${mailbox}.`,
      });
      if (recovered === undefined) {
        throw error;
      }
      fail(recovered.outcome);
      logCalendarRecovered(this.logger, {
        userProfileId: userProfileIdString,
        mailbox,
        calendarId: input.calendarId,
        outcome: recovered.outcome,
        msg: `create_event ${recovered.outcome}`,
        err: error,
      });
      return {
        success: false,
        message: recovered.message,
        transactionId,
        ...(recovered.consentRequired === true ? { consentRequired: true } : {}),
      };
    }
  }

  private async resolveDefaultCalendarId(
    client: Client,
    mailbox: string,
    userProfileId: string,
  ): Promise<string> {
    const raw = await client.api(defaultCalendarPath(mailbox)).select('id').get();
    const calendarId = DefaultCalendarSchema.parse(raw).id;
    this.logger.debug({
      userProfileId,
      mailbox,
      calendarId,
      msg: 'create_event resolved default calendar',
    });
    return calendarId;
  }
}

function accessPathForMailbox(mailbox: string, callerEmail: string): CalendarAccessPath {
  return mailbox.toLowerCase() === callerEmail.toLowerCase() ? 'ownMailbox' : 'ownerMailbox';
}

function newTransactionId(): string {
  return randomUUID().replaceAll('-', '');
}

function uniqueAttendees(attendees: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const attendee of attendees) {
    const trimmed = attendee.trim();
    const key = trimmed.toLowerCase();
    if (!SmtpAddressSchema.safeParse(trimmed).success || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(trimmed);
  }
  return result;
}
