import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import { isDelegatedAccessNotAvailableError } from '~/features/delegated-access/utils/is-delegated-access-not-available-error';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetMailboxTimezoneQuery } from '~/features/user-utils/get-mailbox-timezone.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { nameSimilarity } from '~/utils/name-similarity-score';
import {
  type RelativeRange,
  type ResolvedWindow,
  resolveQueryWindow,
} from '~/utils/relative-range';
import { resolveIanaTimezone } from '~/utils/resolve-iana-timezone';
import {
  CalendarRef,
  type EventRef,
  GraphEvent,
  GraphEventCollectionSchema,
} from './calendar.schemas';
import { ListCalendarsQuery } from './list-calendars.query';
import { summariseRecurrence } from './summarise-recurrence';
import { calendarGraphLimit } from './utils/calendar-graph-limit';
import { calendarMailbox, calendarViewPath } from './utils/calendar-graph-path';
import { dateWindowFromSearchInput } from './utils/date-window-bucket';

const EVENT_SELECT =
  'id,subject,body,start,end,location,attendees,organizer,onlineMeeting,onlineMeetingUrl,webLink,isCancelled,isAllDay,sensitivity,categories,type,seriesMasterId,recurrence,showAs';
const CALENDAR_VIEW_TOP = 100;
const MAX_CALENDAR_VIEW_PAGES = 5;
const MAX_EVENTS = 100;
const BODY_MAX_CHARS = 4000;
const TEXT_FILTER_SIMILARITY = 0.75;
const UTC = 'UTC';

interface CalendarEventAttendee {
  name: string | null;
  email: string | null;
  response: string | null;
  type: string | null;
}

interface CalendarEventDateTime {
  dateTime: string;
  timeZone: string | null;
}

interface CalendarEvent {
  subject: string | null;
  body: string;
  bodyTruncated: boolean;
  start: CalendarEventDateTime;
  end: CalendarEventDateTime;
  location: string | null;
  joinUrl: string | null;
  attendees: CalendarEventAttendee[];
  organizerName: string | null;
  organizerEmail: string | null;
  isCancelled: boolean;
  isAllDay: boolean;
  isPrivate: boolean;
  sensitivity: string | null;
  categories: string[];
  recurrence: string | null;
  seriesMasterId: string | null;
  type: string | null;
  showAs: string | null;
  webLink: string | null;
  calendarName: string;
  eventRef: EventRef;
}

export interface SearchCalendarEventsQueryOutput {
  success: boolean;
  message: string;
  events?: CalendarEvent[];
  searchNotes?: string[];
  resolvedWindow?: ResolvedWindow;
  consentRequired?: boolean;
}

export interface SearchCalendarEventsQueryInput {
  mailbox?: string;
  attendee?: string;
  subject?: string;
  category?: string;
  range?: RelativeRange;
  startDateTime?: string;
  endDateTime?: string;
  now?: Temporal.ZonedDateTime;
}

@Injectable()
export class SearchCalendarEventsQuery {
  private readonly logger = new Logger(SearchCalendarEventsQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly listCalendarsQuery: ListCalendarsQuery,
    private readonly getMailboxTimezoneQuery: GetMailboxTimezoneQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: SearchCalendarEventsQueryInput,
  ): Promise<SearchCalendarEventsQueryOutput> {
    return this.calendarMetrics.measureSearch(
      {
        dateWindow: dateWindowFromSearchInput(input),
        hasAttendeeFilter: input.attendee !== undefined,
        hasSubjectFilter: input.subject !== undefined,
        hasCategoryFilter: input.category !== undefined,
      },
      () => this.search(userProfileId, input),
    );
  }

  private async search(
    userProfileId: UserProfileTypeID,
    input: SearchCalendarEventsQueryInput,
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
    const mappedIana =
      mailboxTimeZone === undefined ? undefined : resolveIanaTimezone(mailboxTimeZone);
    const ianaTimeZone = mappedIana ?? UTC;
    const timezoneNotes: string[] = [];
    if (mailboxTimeZone === undefined) {
      timezoneNotes.push('Mailbox timezone was unavailable; times are requested in UTC.');
    } else if (mappedIana === undefined) {
      timezoneNotes.push(
        `Mailbox timezone "${mailboxTimeZone}" could not be mapped to IANA; relative windows are resolved in UTC.`,
      );
    }
    const { calendars, notes: mailboxNotes } = this.filterOutNonAccessibleCalendars({
      calendars: listed.calendars ?? [],
      mailbox: input.mailbox,
      callerEmail: userProfile.email,
    });
    const clock = input.now ?? Temporal.Now.zonedDateTimeISO(ianaTimeZone);
    const resolvedWindow = resolveQueryWindow({
      range: input.range,
      startDateTime: input.startDateTime,
      endDateTime: input.endDateTime,
      now: clock,
    });
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

    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const { events, notes: searchNotes } = await this.searchCalendars({
      client,
      userId: userProfile.id,
      callerEmail: userProfile.email,
      calendars,
      filters: input,
      timeZone: outlookTimeZone,
      resolvedWindow,
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
  }

  private filterOutNonAccessibleCalendars(input: {
    calendars: CalendarRef[];
    mailbox: string | undefined;
    callerEmail: string;
  }): { calendars: CalendarRef[]; notes: string[] } {
    if (input.mailbox === undefined) {
      return { calendars: input.calendars, notes: [] };
    }
    const target = input.mailbox.toLowerCase();
    const matched = input.calendars.filter((calendar) => {
      if (calendar.ownerEmail?.toLowerCase() === target) {
        return true;
      }
      return calendar.isOwn && input.callerEmail.toLowerCase() === target;
    });
    return {
      calendars: matched,
      notes: matched.length === 0 ? [`No calendars matched mailbox ${input.mailbox}.`] : [],
    };
  }

  private async searchCalendars(input: {
    client: Client;
    userId: string;
    callerEmail: string;
    calendars: CalendarRef[];
    filters: SearchCalendarEventsQueryInput;
    timeZone: string;
    resolvedWindow: ResolvedWindow;
  }): Promise<{ events: CalendarEvent[]; notes: string[] }> {
    using limit = calendarGraphLimit(input.userId);
    const perCalendar = await Promise.all(
      input.calendars.map((calendar) =>
        limit(
          async (): Promise<{
            events: CalendarEvent[];
            notes: string[];
            fetched: number;
            calendar: CalendarRef;
          }> => {
            try {
              const fetched = await this.fetchEvents({
                client: input.client,
                callerEmail: input.callerEmail,
                calendar,
                filters: input.filters,
                timeZone: input.timeZone,
                resolvedWindow: input.resolvedWindow,
              });
              return {
                events: fetched.events,
                notes: fetched.notes,
                fetched: fetched.fetched,
                calendar,
              };
            } catch (error) {
              if (isDelegatedAccessNotAvailableError(error)) {
                return {
                  events: [],
                  notes: [
                    `Could not read calendar "${calendar.name}"${calendar.ownerEmail ? ` (${calendar.ownerEmail})` : ''}.`,
                  ],
                  fetched: 0,
                  calendar,
                };
              }
              throw error;
            }
          },
        ),
      ),
    );
    const calendarNotes = perCalendar.flatMap((result) => result.notes);
    const matched = perCalendar
      .flatMap((result) => result.events.map((event) => ({ event, calendar: result.calendar })))
      .sort((left, right) => left.event.start.dateTime.localeCompare(right.event.start.dateTime));
    const truncated = matched.length > MAX_EVENTS;
    const kept = truncated ? matched.slice(0, MAX_EVENTS) : matched;
    const totalFetched = perCalendar.reduce((sum, result) => sum + result.fetched, 0);
    const totalReturned = kept.length;
    this.logger.log({
      msg: 'search_calendar_events Graph fan-out',
      totalFetched,
      totalReturned,
      truncated,
    });
    const notes = [
      ...calendarNotes,
      ...(kept.some(({ event, calendar }) => event.isPrivate && !calendar.canViewPrivateItems)
        ? ['Some events are marked private; details may be redacted.']
        : []),
      ...(truncated ? [`Results truncated to ${MAX_EVENTS} events.`] : []),
    ];
    return { events: kept.map(({ event }) => event), notes };
  }

  private async fetchEvents(input: {
    client: Client;
    callerEmail: string;
    calendar: CalendarRef;
    filters: SearchCalendarEventsQueryInput;
    timeZone: string;
    resolvedWindow: ResolvedWindow;
  }): Promise<{ events: CalendarEvent[]; notes: string[]; fetched: number }> {
    const events: CalendarEvent[] = [];
    const prefer = `outlook.timezone="${input.timeZone}", outlook.body-content-type="text", IdType="ImmutableId"`;
    let nextPath: string | undefined = calendarViewPath({
      calendarId: input.calendar.calendarId,
      mailboxEmail: calendarMailbox({
        calendar: input.calendar,
        callerEmail: input.callerEmail,
      }),
    });
    let isFirst = true;
    let pages = 0;
    let fetched = 0;

    while (nextPath && pages < MAX_CALENDAR_VIEW_PAGES) {
      const request = input.client.api(nextPath).header('Prefer', prefer);
      const raw = isFirst
        ? await request
            .query({
              startDateTime: input.resolvedWindow.startDateTime,
              endDateTime: input.resolvedWindow.endDateTime,
            })
            .select(EVENT_SELECT)
            .top(CALENDAR_VIEW_TOP)
            .get()
        : await request.get();
      isFirst = false;
      pages += 1;
      const parsed = GraphEventCollectionSchema.parse(raw);
      for (const item of parsed.value) {
        fetched += 1;
        const event = this.toCalendarEvent({
          event: item,
          calendar: input.calendar,
          callerEmail: input.callerEmail,
        });
        if (this.matchesFilters(event, input.filters)) {
          events.push(event);
        }
      }
      nextPath = parsed['@odata.nextLink'];
    }

    return {
      events,
      fetched,
      notes:
        nextPath === undefined
          ? []
          : [
              `Stopped paging calendar "${input.calendar.name}" after ${MAX_CALENDAR_VIEW_PAGES} pages.`,
            ],
    };
  }

  private matchesFilters(event: CalendarEvent, input: SearchCalendarEventsQueryInput): boolean {
    if (input.subject !== undefined && !matchesText(event.subject ?? '', input.subject)) {
      return false;
    }
    if (input.category !== undefined) {
      const wanted = input.category.toLowerCase();
      if (!event.categories.some((category) => category.toLowerCase() === wanted)) {
        return false;
      }
    }
    if (input.attendee !== undefined) {
      const wanted = input.attendee;
      const hit =
        matchesPerson(event.organizerName, event.organizerEmail, wanted) ||
        event.attendees.some((attendee) => matchesPerson(attendee.name, attendee.email, wanted));
      if (!hit) {
        return false;
      }
    }
    return true;
  }

  private toCalendarEvent(input: {
    event: GraphEvent;
    calendar: CalendarRef;
    callerEmail: string;
  }): CalendarEvent {
    const rawBody = input.event.body?.content ?? '';
    const bodyTruncated = rawBody.length > BODY_MAX_CHARS;
    return {
      subject: input.event.subject ?? null,
      body: bodyTruncated ? rawBody.slice(0, BODY_MAX_CHARS) : rawBody,
      bodyTruncated,
      start: {
        dateTime: input.event.start?.dateTime ?? '',
        timeZone: input.event.start?.timeZone ?? null,
      },
      end: {
        dateTime: input.event.end?.dateTime ?? '',
        timeZone: input.event.end?.timeZone ?? null,
      },
      location: input.event.location?.displayName ?? null,
      joinUrl: input.event.onlineMeeting?.joinUrl ?? input.event.onlineMeetingUrl ?? null,
      attendees: (input.event.attendees ?? []).map((attendee) => ({
        name: attendee.emailAddress?.name ?? null,
        email: attendee.emailAddress?.address ?? null,
        response: attendee.status?.response ?? null,
        type: attendee.type ?? null,
      })),
      organizerName: input.event.organizer?.emailAddress?.name ?? null,
      organizerEmail: input.event.organizer?.emailAddress?.address ?? null,
      isCancelled: input.event.isCancelled ?? false,
      isAllDay: input.event.isAllDay ?? false,
      isPrivate:
        input.event.sensitivity === 'private' || input.event.sensitivity === 'confidential',
      sensitivity: input.event.sensitivity ?? null,
      categories: input.event.categories ?? [],
      recurrence: summariseRecurrence(input.event.recurrence?.pattern),
      seriesMasterId: input.event.seriesMasterId ?? null,
      type: input.event.type ?? null,
      showAs: input.event.showAs ?? null,
      webLink: input.event.webLink ?? null,
      calendarName: input.calendar.name,
      eventRef: {
        eventId: input.event.id,
        calendarId: input.calendar.calendarId,
        accessPath: input.calendar.accessPath,
        mailbox: calendarMailbox({
          calendar: input.calendar,
          callerEmail: input.callerEmail,
        }),
      },
    };
  }
}

function matchesPerson(name: string | null, email: string | null, wanted: string): boolean {
  const emailHit = email?.toLowerCase().includes(wanted.toLowerCase()) ?? false;
  return emailHit || matchesText(name ?? '', wanted);
}

function matchesText(haystack: string, needle: string): boolean {
  if (haystack.toLowerCase().includes(needle.toLowerCase())) {
    return true;
  }
  return nameSimilarity(needle, haystack) >= TEXT_FILTER_SIMILARITY;
}
