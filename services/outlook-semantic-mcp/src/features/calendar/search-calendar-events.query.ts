import assert from 'node:assert';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import pLimit from 'p-limit';
import * as z from 'zod';
import { UserProfile } from '~/db';
import { isDelegatedAccessNotAvailableError } from '~/features/delegated-access/utils/is-delegated-access-not-available-error';
import { GetMailboxTimezoneQuery } from '~/features/user-utils/get-mailbox-timezone.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import {
  AllDelegatesFailedError,
  MsGraphClientResolver,
  NoDelegatesFoundError,
} from '~/msgraph/ms-graph-client-resolver.service';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { resolveIanaTimezone } from '~/utils/resolve-iana-timezone';
import {
  CalendarRef,
  EventRefSchema,
  GraphEvent,
  GraphEventCollectionSchema,
} from './calendar.schemas';
import { calendarViewPath } from './calendar-view-path';
import { ListCalendarsQuery } from './list-calendars.query';
import type { RelativeRange } from './relative-range';
import { formatGraphInstant, type ResolvedWindow, resolveRange } from './resolve-range';
import { summariseRecurrence } from './summarise-recurrence';

const EVENT_SELECT =
  'id,subject,body,start,end,location,attendees,organizer,isOnlineMeeting,onlineMeeting,onlineMeetingUrl,webLink,isCancelled,isAllDay,sensitivity,categories,type,seriesMasterId,recurrence,showAs';
const CALENDAR_VIEW_TOP = 100;
const MAX_EVENTS = 100;
const BODY_MAX_CHARS = 4000;
const CALENDAR_VIEW_CONCURRENCY = 5;
const UTC = 'UTC';

const AttendeeSchema = z.object({
  name: z.string().nullable().describe('Display name of the attendee, or null if omitted.'),
  email: z.string().nullable().describe('SMTP address of the attendee, or null if omitted.'),
  response: z
    .string()
    .nullable()
    .describe(
      'Attendee response: none, organizer, tentativelyAccepted, accepted, declined, or notResponded.',
    ),
  type: z
    .string()
    .nullable()
    .describe('Attendee type: required, optional, or resource. Null if Graph omitted it.'),
});

const DateTimeSchema = z.object({
  dateTime: z
    .string()
    .describe('Local date and time of the boundary as returned by Graph, without a trailing Z.'),
  timeZone: z
    .string()
    .nullable()
    .describe('Windows or IANA timezone Graph attached to this boundary, or null if omitted.'),
});

export const CalendarEventSchema = z.object({
  subject: z.string().nullable().describe('Event subject. Null when Graph omitted or redacted it.'),
  body: z
    .string()
    .describe(
      'Plain-text event body, already converted by Graph. May be truncated; see bodyTruncated.',
    ),
  bodyTruncated: z.boolean().describe('True when body was cut to the per-event character cap.'),
  start: DateTimeSchema.describe('Event start.'),
  end: DateTimeSchema.describe('Event end.'),
  location: z
    .string()
    .nullable()
    .describe('Location display name, or null when the event has no location.'),
  joinUrl: z
    .string()
    .nullable()
    .describe('Online meeting join URL when present. Never construct a Teams URL yourself.'),
  attendees: z
    .array(AttendeeSchema)
    .describe('All attendees with per-person response status. Not capped.'),
  organizerName: z.string().nullable().describe('Organizer display name, or null if omitted.'),
  organizerEmail: z.string().nullable().describe('Organizer SMTP address, or null if omitted.'),
  isCancelled: z.boolean().describe('True when the occurrence or event has been cancelled.'),
  isAllDay: z.boolean().describe('True when the event lasts the whole day.'),
  isPrivate: z
    .boolean()
    .describe('True when sensitivity is private or confidential. Details may already be redacted.'),
  categories: z.array(z.string()).describe('Outlook categories on the event.'),
  recurrence: z
    .string()
    .nullable()
    .describe('Short human summary of the series pattern, or null for a one-off event.'),
  seriesMasterId: z
    .string()
    .nullable()
    .describe('Internal series master ID for occurrences. Never display to the user.'),
  type: z
    .string()
    .nullable()
    .describe('Graph event type: singleInstance, occurrence, exception, or seriesMaster.'),
  showAs: z
    .string()
    .nullable()
    .describe(
      'Free/busy shown to others: free, tentative, busy, oof, workingElsewhere, or unknown.',
    ),
  webLink: z
    .string()
    .nullable()
    .describe(
      'Outlook web link for this event. The only user-facing URL besides joinUrl. Empty means render the subject as plain text.',
    ),
  calendarName: z.string().describe('Display name of the calendar this event was read from.'),
  eventRef: EventRefSchema.describe(
    'Internal handle for this event. Pass it verbatim to other calendar tools. Never display it.',
  ),
});

export const SearchCalendarEventsQueryOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when the search ran. False when Graph access failed before any calendar was queried.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  events: z
    .array(CalendarEventSchema)
    .optional()
    .describe('Matching events, sorted by start time, capped at 100.'),
  searchNotes: z
    .array(z.string())
    .optional()
    .describe(
      'Notes about dropped calendars, truncated results, or timezone fallback. Display after the results.',
    ),
  resolvedWindow: z
    .object({
      startDateTime: z
        .string()
        .describe('Absolute start sent to Graph, including timezone offset.'),
      endDateTime: z.string().describe('Absolute end sent to Graph, including timezone offset.'),
      timeZone: z
        .string()
        .describe(
          'IANA timezone the window was resolved in, or UTC when the mailbox timezone was unavailable.',
        ),
      serverCurrentDateTime: z
        .string()
        .describe('Server clock in that timezone when the window was resolved, including offset.'),
      interpretation: z
        .string()
        .describe(
          'Human description of the window, e.g. "next week = Mon 2026-08-31 00:00 to Sun 2026-09-06 23:59 (Europe/Zurich)". State this when a relative range was used.',
        ),
    })
    .optional()
    .describe('The calendarView window actually queried.'),
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

export type SearchCalendarEventsQueryOutput = z.infer<typeof SearchCalendarEventsQueryOutputSchema>;

export interface SearchCalendarEventsQueryInput {
  mailbox?: string;
  attendee?: string;
  subject?: string;
  category?: string;
  range?: RelativeRange;
  startDateTime?: string;
  endDateTime?: string;
}

@Injectable()
export class SearchCalendarEventsQuery {
  private readonly logger = new Logger(SearchCalendarEventsQuery.name);

  public constructor(
    private readonly msGraphClientResolver: MsGraphClientResolver,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly listCalendarsQuery: ListCalendarsQuery,
    private readonly getMailboxTimezoneQuery: GetMailboxTimezoneQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: SearchCalendarEventsQueryInput,
    now?: Temporal.ZonedDateTime,
  ): Promise<SearchCalendarEventsQueryOutput> {
    const listed = await this.listCalendarsQuery.run(userProfileId);
    if (!listed.success) {
      return {
        success: false,
        message: listed.message,
        consentRequired: listed.consentRequired,
      };
    }

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const mailboxTimeZone = await this.getMailboxTimezoneQuery.run(userProfileId);
    const outlookTimeZone = mailboxTimeZone ?? UTC;
    const ianaTimeZone =
      mailboxTimeZone === undefined ? UTC : (resolveIanaTimezone(mailboxTimeZone) ?? UTC);
    const timezoneNotes =
      mailboxTimeZone === undefined
        ? ['Mailbox timezone was unavailable; times are requested in UTC.']
        : [];
    const { calendars, notes: mailboxNotes } = this.selectCalendars(
      listed.calendars ?? [],
      input.mailbox,
      userProfile.email,
    );
    const clock = now ?? Temporal.Now.zonedDateTimeISO(ianaTimeZone);
    const resolvedWindow = this.resolveWindow(input, ianaTimeZone, clock);
    const prefixNotes = [...timezoneNotes, ...mailboxNotes];
    if (calendars.length === 0) {
      return {
        success: true,
        message: 'No calendars matched the search.',
        events: [],
        searchNotes: prefixNotes.length > 0 ? prefixNotes : undefined,
        resolvedWindow,
      };
    }

    try {
      const { events, notes: searchNotes } = await this.msGraphClientResolver.run({
        userProfile,
        sharedMailboxConfig: { throwIfNoDelegates: true },
        fn: ({ client }) =>
          this.searchCalendars(
            client,
            userProfile,
            calendars,
            input,
            outlookTimeZone,
            resolvedWindow,
          ),
      });
      const notes = [...prefixNotes, ...searchNotes];
      return {
        success: true,
        message:
          events.length === 0
            ? 'No events matched the search.'
            : `Found ${events.length} event${events.length === 1 ? '' : 's'}.`,
        events,
        searchNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow,
      };
    } catch (error) {
      if (error instanceof NoDelegatesFoundError || error instanceof AllDelegatesFailedError) {
        this.logger.warn({ msg: 'Shared mailbox calendar search failed', err: error });
        return {
          success: false,
          message:
            'Could not reach this shared mailbox through a connected Outlook account. Ask a mailbox owner to reconnect.',
        };
      }
      throw error;
    }
  }

  private selectCalendars(
    calendars: CalendarRef[],
    mailbox: string | undefined,
    callerEmail: string,
  ): { calendars: CalendarRef[]; notes: string[] } {
    if (mailbox === undefined) {
      return { calendars, notes: [] };
    }
    const target = mailbox.toLowerCase();
    const matched = calendars.filter((calendar) => {
      if (calendar.ownerEmail?.toLowerCase() === target) {
        return true;
      }
      return calendar.isOwn && callerEmail.toLowerCase() === target;
    });
    return {
      calendars: matched,
      notes: matched.length === 0 ? [`No calendars matched mailbox ${mailbox}.`] : [],
    };
  }

  private resolveWindow(
    input: SearchCalendarEventsQueryInput,
    ianaTimeZone: string,
    clock: Temporal.ZonedDateTime,
  ): ResolvedWindow {
    if (input.range !== undefined) {
      return resolveRange(input.range, ianaTimeZone, clock);
    }
    assert.ok(
      input.startDateTime !== undefined && input.endDateTime !== undefined,
      'range or an absolute startDateTime and endDateTime is required',
    );
    return {
      startDateTime: input.startDateTime,
      endDateTime: input.endDateTime,
      timeZone: ianaTimeZone,
      serverCurrentDateTime: formatGraphInstant(clock),
      interpretation: `absolute window ${input.startDateTime} to ${input.endDateTime} (${ianaTimeZone})`,
    };
  }

  private async searchCalendars(
    client: Client,
    userProfile: NonNullishProps<UserProfile, 'email'>,
    calendars: CalendarRef[],
    input: SearchCalendarEventsQueryInput,
    timeZone: string,
    resolvedWindow: ResolvedWindow,
  ): Promise<{ events: z.infer<typeof CalendarEventSchema>[]; notes: string[] }> {
    const limit = pLimit(CALENDAR_VIEW_CONCURRENCY);
    const perCalendar = await Promise.all(
      calendars.map((calendar) =>
        limit(
          async (): Promise<{ events: z.infer<typeof CalendarEventSchema>[]; note?: string }> => {
            try {
              return {
                events: await this.fetchEvents(
                  client,
                  userProfile,
                  calendar,
                  timeZone,
                  resolvedWindow,
                ),
              };
            } catch (error) {
              if (isDelegatedAccessNotAvailableError(error)) {
                return {
                  events: [],
                  note: `Could not read calendar "${calendar.name}"${calendar.ownerEmail ? ` (${calendar.ownerEmail})` : ''}.`,
                };
              }
              throw error;
            }
          },
        ),
      ),
    );
    const notes = perCalendar.flatMap((result) => (result.note === undefined ? [] : [result.note]));
    const matched = perCalendar
      .flatMap((result) => result.events)
      .filter((event) => this.matchesFilters(event, input))
      .sort((left, right) => left.start.dateTime.localeCompare(right.start.dateTime));
    if (matched.length > MAX_EVENTS) {
      return {
        events: matched.slice(0, MAX_EVENTS),
        notes: [...notes, `Results truncated to ${MAX_EVENTS} events.`],
      };
    }
    return { events: matched, notes };
  }

  private async fetchEvents(
    client: Client,
    userProfile: NonNullishProps<UserProfile, 'email'>,
    calendar: CalendarRef,
    timeZone: string,
    resolvedWindow: ResolvedWindow,
  ) {
    const events = [];
    const prefer = `outlook.timezone="${timeZone}", outlook.body-content-type="text", IdType="ImmutableId"`;
    let nextPath: string | undefined = calendarViewPath(calendar, userProfile);
    let isFirst = true;

    while (nextPath) {
      const request = client.api(nextPath).header('Prefer', prefer);
      const raw = isFirst
        ? await request
            .query({
              startDateTime: resolvedWindow.startDateTime,
              endDateTime: resolvedWindow.endDateTime,
            })
            .select(EVENT_SELECT)
            .top(CALENDAR_VIEW_TOP)
            .get()
        : await request.get();
      isFirst = false;
      const parsed = GraphEventCollectionSchema.parse(raw);
      for (const item of parsed.value) {
        events.push(this.toCalendarEvent(item, calendar, userProfile.email));
      }
      nextPath = parsed['@odata.nextLink'];
    }

    return events;
  }

  private matchesFilters(
    event: z.infer<typeof CalendarEventSchema>,
    input: SearchCalendarEventsQueryInput,
  ): boolean {
    if (input.subject !== undefined) {
      const haystack = event.subject?.toLowerCase() ?? '';
      if (!haystack.includes(input.subject.toLowerCase())) {
        return false;
      }
    }
    if (input.category !== undefined) {
      const wanted = input.category.toLowerCase();
      if (!event.categories.some((category) => category.toLowerCase() === wanted)) {
        return false;
      }
    }
    if (input.attendee !== undefined) {
      const wanted = input.attendee.toLowerCase();
      const hit = event.attendees.some((attendee) => {
        const email = attendee.email?.toLowerCase() ?? '';
        const name = attendee.name?.toLowerCase() ?? '';
        return email.includes(wanted) || name.includes(wanted);
      });
      if (!hit) {
        return false;
      }
    }
    return true;
  }

  private toCalendarEvent(
    event: GraphEvent,
    calendar: CalendarRef,
    callerEmail: string,
  ): z.infer<typeof CalendarEventSchema> {
    const rawBody = event.body?.content ?? '';
    const bodyTruncated = rawBody.length > BODY_MAX_CHARS;
    const mailbox =
      calendar.accessPath === 'ownerMailbox' ? (calendar.ownerEmail ?? callerEmail) : callerEmail;

    return {
      subject: event.subject ?? null,
      body: bodyTruncated ? rawBody.slice(0, BODY_MAX_CHARS) : rawBody,
      bodyTruncated,
      start: {
        dateTime: event.start?.dateTime ?? '',
        timeZone: event.start?.timeZone ?? null,
      },
      end: {
        dateTime: event.end?.dateTime ?? '',
        timeZone: event.end?.timeZone ?? null,
      },
      location: event.location?.displayName ?? null,
      joinUrl: event.onlineMeeting?.joinUrl ?? event.onlineMeetingUrl ?? null,
      attendees: (event.attendees ?? []).map((attendee) => ({
        name: attendee.emailAddress?.name ?? null,
        email: attendee.emailAddress?.address ?? null,
        response: attendee.status?.response ?? null,
        type: attendee.type ?? null,
      })),
      organizerName: event.organizer?.emailAddress?.name ?? null,
      organizerEmail: event.organizer?.emailAddress?.address ?? null,
      isCancelled: event.isCancelled ?? false,
      isAllDay: event.isAllDay ?? false,
      isPrivate: event.sensitivity === 'private' || event.sensitivity === 'confidential',
      categories: event.categories ?? [],
      recurrence: summariseRecurrence(event.recurrence?.pattern),
      seriesMasterId: event.seriesMasterId ?? null,
      type: event.type ?? null,
      showAs: event.showAs ?? null,
      webLink: event.webLink ?? null,
      calendarName: calendar.name,
      eventRef: {
        eventId: event.id,
        calendarId: calendar.calendarId,
        accessPath: calendar.accessPath,
        mailbox,
      },
    };
  }
}
