import assert from 'node:assert';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import * as z from 'zod';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import type { EventRef } from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
} from './utils/calendar-graph-errors';
import { eventPath } from './utils/calendar-graph-path';
import { mapIsoToGraphDateTimeTimeZone } from './utils/map-iso-to-graph-date-time-time-zone';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

const MAX_ATTENDEES = 20;

const UpdatedEventSchema = z.object({
  id: z.string(),
  subject: z.string().optional().nullable(),
  start: z.object({ dateTime: z.string().optional(), timeZone: z.string().optional() }).nullish(),
  end: z.object({ dateTime: z.string().optional(), timeZone: z.string().optional() }).nullish(),
  webLink: z.string().nullish(),
  onlineMeeting: z.object({ joinUrl: z.string().optional() }).nullish(),
  onlineMeetingUrl: z.string().nullish(),
  location: z.object({ displayName: z.string().optional() }).nullish(),
});

export interface UpdateEventCommandInput {
  eventRef: EventRef;
  targetEventId: string;
  subject?: string;
  startDateTime?: string;
  endDateTime?: string;
  attendees?: string[];
  location?: string;
  body?: string;
  isOnlineMeeting?: boolean;
  notifyAttendees: boolean;
}

export interface UpdateEventCommandOutput {
  success: boolean;
  message: string;
  eventRef?: EventRef;
  subject?: string | null;
  start?: { dateTime: string; timeZone: string | null };
  end?: { dateTime: string; timeZone: string | null };
  location?: string | null;
  joinUrl?: string | null;
  webLink?: string | null;
  consentRequired?: boolean;
}

@Injectable()
export class UpdateEventCommand {
  private readonly logger = new Logger(UpdateEventCommand.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly resolveMailboxTimezoneQuery: ResolveMailboxTimezoneQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: UpdateEventCommandInput,
  ): Promise<UpdateEventCommandOutput> {
    assert.ok(
      SmtpAddressSchema.safeParse(input.eventRef.mailbox).success,
      'eventRef.mailbox must already be an SMTP address',
    );
    assert.ok(input.eventRef.calendarId.length > 0, 'eventRef.calendarId must already be set');
    assert.ok(input.targetEventId.length > 0, 'targetEventId must already be set');
    const patch = buildPatch(input);
    const hasTimeChange = input.startDateTime !== undefined || input.endDateTime !== undefined;
    assert.ok(
      Object.keys(patch).length > 0 || hasTimeChange,
      'update must already include at least one field',
    );

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const mailbox = input.eventRef.mailbox;
    const { ianaTimeZone, outlookTimeZone } =
      await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const path = eventPath({
      mailboxEmail: mailbox,
      calendarId: input.eventRef.calendarId,
      eventId: input.targetEventId,
    });
    const startTime =
      input.startDateTime !== undefined
        ? mapIsoToGraphDateTimeTimeZone({
            iso: input.startDateTime,
            ianaTimeZone,
            windowsTimeZone: outlookTimeZone,
          })
        : undefined;
    const endTime =
      input.endDateTime !== undefined
        ? mapIsoToGraphDateTimeTimeZone({
            iso: input.endDateTime,
            ianaTimeZone,
            windowsTimeZone: outlookTimeZone,
          })
        : undefined;

    try {
      const raw = await client
        .api(path)
        .header('Prefer', `outlook.timezone="${outlookTimeZone}", IdType="ImmutableId"`)
        .patch({
          ...patch,
          ...(startTime !== undefined ? { start: startTime } : {}),
          ...(endTime !== undefined ? { end: endTime } : {}),
        });
      const updated = UpdatedEventSchema.parse(raw);
      this.logger.log({ msg: 'update_event', mailbox, calendarId: input.eventRef.calendarId });
      return {
        success: true,
        message: input.notifyAttendees
          ? 'Updated the event. Attendees were notified immediately.'
          : 'Updated the event.',
        eventRef: {
          eventId: updated.id,
          calendarId: input.eventRef.calendarId,
          accessPath: input.eventRef.accessPath,
          mailbox,
        },
        subject: updated.subject ?? input.subject?.trim() ?? null,
        start: {
          dateTime: updated.start?.dateTime ?? startTime?.dateTime ?? '',
          timeZone: updated.start?.timeZone ?? startTime?.timeZone ?? null,
        },
        end: {
          dateTime: updated.end?.dateTime ?? endTime?.dateTime ?? '',
          timeZone: updated.end?.timeZone ?? endTime?.timeZone ?? null,
        },
        location: updated.location?.displayName ?? input.location?.trim() ?? null,
        joinUrl: updated.onlineMeeting?.joinUrl ?? updated.onlineMeetingUrl ?? null,
        webLink: updated.webLink ?? null,
      };
    } catch (error) {
      return mapWriteError({
        error,
        mailbox,
        callerEmail: userProfile.email,
        deniedDelegated: `Could not update an event on mailbox ${mailbox}.`,
      });
    }
  }
}

function buildPatch(input: UpdateEventCommandInput): Record<string, unknown> {
  if (input.startDateTime !== undefined && input.endDateTime !== undefined) {
    const start = Temporal.Instant.from(input.startDateTime);
    const end = Temporal.Instant.from(input.endDateTime);
    assert.ok(
      Temporal.Instant.compare(end, start) > 0,
      'endDateTime must already be after startDateTime',
    );
  }
  const attendees = input.attendees !== undefined ? uniqueAttendees(input.attendees) : undefined;
  if (attendees !== undefined) {
    assert.ok(
      attendees.length <= MAX_ATTENDEES,
      'attendees must already be at most 20 SMTP addresses',
    );
  }
  return {
    ...(input.subject !== undefined && input.subject.trim() !== ''
      ? { subject: input.subject.trim() }
      : {}),
    ...(input.body !== undefined ? { body: { contentType: 'text', content: input.body } } : {}),
    ...(input.location !== undefined ? { location: { displayName: input.location.trim() } } : {}),
    ...(attendees !== undefined
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
  };
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

function mapWriteError(input: {
  error: unknown;
  mailbox: string;
  callerEmail: string;
  deniedDelegated: string;
}): UpdateEventCommandOutput {
  if (input.error instanceof GraphError && input.error.statusCode === 404) {
    return {
      success: false,
      message: 'That event was not found. Search again and pass eventRef without changing it.',
    };
  }
  if (input.error instanceof GraphError && input.error.statusCode === 400) {
    return {
      success: false,
      message: 'Graph rejected the update. Check the times and fields and try again.',
    };
  }
  if (isCalendarPermissionDeniedError(input.error)) {
    if (input.mailbox.toLowerCase() === input.callerEmail.toLowerCase()) {
      return {
        success: false,
        message: new CalendarConsentRequiredError().message,
        consentRequired: true,
      };
    }
    return { success: false, message: input.deniedDelegated };
  }
  throw input.error;
}
