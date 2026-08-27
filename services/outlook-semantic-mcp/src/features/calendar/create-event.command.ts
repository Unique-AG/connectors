import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import {
  type CalendarMetricErrorType,
  CalendarMetricsService,
} from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import { type EventRef, GraphWrittenEventSchema } from './calendar.schemas';
import { createEventPath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  recoverCalendarGraphError,
} from './utils/calendar-observability';
import type { CalendarRefInput } from './utils/calendar-ref.schema';
import { graphEventBody } from './utils/graph-event-body';
import { mapIsoToGraphDateTimeTimeZone } from './utils/map-iso-to-graph-date-time-time-zone';
import { SmtpAddressSchema, uniqueSmtpAddresses } from './utils/smtp-address.schema';

const TRANSACTION_ID_MAX = 32;

export interface CreateEventCommandInput {
  subject: string;
  startDateTime: string;
  endDateTime: string;
  attendees?: string[];
  location?: string;
  body?: string;
  isOnlineMeeting?: boolean;
  calendarRef: CalendarRefInput;
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
  errorType?: CalendarMetricErrorType;
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
      mailbox: obfuscateEmail(input.calendarRef.mailbox),
      calendarId: input.calendarRef.calendarId,
      attendeeCount: input.attendees?.length ?? 0,
      msg: 'create_event started',
    });
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox: input.calendarRef.mailbox,
      calendarId: input.calendarRef.calendarId,
      operation: 'create_event',
    });
    return this.calendarMetrics.measureOperation({ operation: 'create_event' }, () =>
      this.create(userProfileId, userProfileIdString, input),
    );
  }

  private async create(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
    input: CreateEventCommandInput,
  ): Promise<CreateEventCommandOutput> {
    assert.ok(input.subject.trim() !== '', 'subject must already be set');
    const start = Temporal.Instant.from(input.startDateTime);
    const end = Temporal.Instant.from(input.endDateTime);
    assert.ok(
      Temporal.Instant.compare(end, start) > 0,
      'endDateTime must already be after startDateTime',
    );
    const attendees = uniqueSmtpAddresses(input.attendees ?? []);
    const transactionId = input.transactionId ?? newTransactionId();
    assert.ok(
      transactionId.length > 0 && transactionId.length <= TRANSACTION_ID_MAX,
      'transactionId must already be 1 to 32 characters',
    );

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    // calendarRef pairs the id with the mailbox it resolves in, so the two cannot be mismatched.
    const mailbox = input.calendarRef.mailbox;
    assert.ok(
      SmtpAddressSchema.safeParse(mailbox).success,
      'mailbox must already be an SMTP address',
    );
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox,
      calendarId: input.calendarRef.calendarId,
      operation: 'create_event',
    });
    const { ianaTimeZone, outlookTimeZone } =
      await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const client = this.graphClientFactory.createClientForUser(userProfile.id);

    try {
      const calendarId = input.calendarRef.calendarId;
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
            ? { body: graphEventBody(input.body) }
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
      const created = GraphWrittenEventSchema.parse(raw);
      this.logger.log({
        userProfileId: userProfileIdString,
        mailbox: obfuscateEmail(mailbox),
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
      return {
        ...recoverCalendarGraphError({
          error,
          logger: this.logger,
          userProfileId: userProfileIdString,
          mailbox,
          callerEmail: userProfile.email,
          calendarId: input.calendarRef.calendarId,
          operation: 'create_event',
          notFoundMessage:
            'That calendar was not found. Call list_calendars again and pass calendarRef without changing it.',
          invalidMessage: 'Graph rejected the event. Check the start and end times and try again.',
          deniedDelegatedMessage: `Could not create an event on mailbox ${mailbox}.`,
        }),
        transactionId,
      };
    }
  }
}

function newTransactionId(): string {
  return randomUUID().replaceAll('-', '');
}
