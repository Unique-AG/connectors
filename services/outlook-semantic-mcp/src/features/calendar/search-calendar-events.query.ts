import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import { isDelegatedAccessNotAvailableError } from '~/features/delegated-access/utils/is-delegated-access-not-available-error';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { dateWindowFromSearchInput } from '~/utils/date-window-bucket';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import {
  type RelativeRange,
  type ResolvedWindow,
  resolveQueryWindow,
} from '~/utils/relative-range';
import { CalendarRef, GraphEventCollectionSchema } from './calendar.schemas';
import { ListCalendarsQuery } from './list-calendars.query';
import { isGraphBadRequestError } from './utils/calendar-graph-errors';
import { calendarGraphLimit } from './utils/calendar-graph-limit';
import { calendarViewPath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  logCalendarRecovered,
} from './utils/calendar-observability';
import type { CalendarRefInput } from './utils/calendar-ref.schema';
import { buildEventGraphFilter, type SubjectFilter } from './utils/event-graph-filter';
import {
  type CalendarEvent,
  mapGraphEventToCalendarEvent,
} from './utils/map-graph-event-to-calendar-event';

const EVENT_SELECT =
  'id,subject,body,start,end,location,attendees,organizer,onlineMeeting,onlineMeetingUrl,webLink,isCancelled,isAllDay,sensitivity,categories,type,seriesMasterId,recurrence,showAs';
const EVENT_ORDER_BY = 'start/dateTime';
const CALENDAR_VIEW_TOP = 100;
const MAX_CALENDAR_VIEW_PAGES = 5;
const MAX_EVENTS = 100;

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
  calendars?: CalendarRefInput[];
  /** Every address must be on the event, as organizer or attendee. */
  attendees?: string[];
  subject?: SubjectFilter;
  /** Every category must be on the event. */
  categories?: string[];
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
    private readonly resolveMailboxTimezoneQuery: ResolveMailboxTimezoneQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: SearchCalendarEventsQueryInput,
  ): Promise<SearchCalendarEventsQueryOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({
      userProfileId: userProfileIdString,
      mailbox: obfuscateEmail(input.mailbox),
      hasAttendeeFilter: hasAttendeeFilter(input),
      hasSubjectFilter: input.subject !== undefined,
      hasCategoryFilter: hasCategoryFilter(input),
      range: input.range,
      msg: 'search_calendar_events started',
    });
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox: input.mailbox,
      operation: 'search_calendar_events',
    });
    return this.calendarMetrics.measureSearch(
      {
        dateWindow: dateWindowFromSearchInput(input),
        hasAttendeeFilter: hasAttendeeFilter(input),
        hasSubjectFilter: input.subject !== undefined,
        hasCategoryFilter: hasCategoryFilter(input),
      },
      () => this.search(userProfileId, userProfileIdString, input),
    );
  }

  private async search(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
    input: SearchCalendarEventsQueryInput,
  ): Promise<SearchCalendarEventsQueryOutput> {
    const listed = await this.listCalendarsQuery.run(userProfileId);
    if (!listed.success) {
      this.logger.debug({
        userProfileId: userProfileIdString,
        msg: 'search_calendar_events list_calendars failed',
      });
      return {
        success: false,
        message: listed.message,
        consentRequired: listed.consentRequired,
      };
    }

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const {
      ianaTimeZone,
      outlookTimeZone,
      notes: timezoneNotes,
    } = await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const { calendars, notes: mailboxNotes } = this.selectCalendars({
      calendars: listed.calendars ?? [],
      requested: input.calendars,
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
    this.logger.debug({
      userProfileId: userProfileIdString,
      mailbox: obfuscateEmail(input.mailbox),
      ianaTimeZone,
      outlookTimeZone,
      interpretation: resolvedWindow.interpretation,
      calendarCount: calendars.length,
      msg: 'search_calendar_events window',
    });
    const prefixNotes = [...timezoneNotes, ...mailboxNotes];
    if (calendars.length === 0) {
      this.logger.debug({
        userProfileId: userProfileIdString,
        mailbox: obfuscateEmail(input.mailbox),
        msg: 'search_calendar_events no calendars matched',
      });
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
      userProfileId: userProfileIdString,
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

  /**
   * Narrows the fan-out. An explicit calendars list wins over the mailbox filter, and is matched
   * against what list_calendars actually returned rather than trusted, so a stale or hand-built
   * calendarRef is reported instead of being sent to Graph.
   */
  private selectCalendars(input: {
    calendars: CalendarRef[];
    requested: CalendarRefInput[] | undefined;
    mailbox: string | undefined;
    callerEmail: string;
  }): { calendars: CalendarRef[]; notes: string[] } {
    if (input.requested !== undefined && input.requested.length > 0) {
      const accessible = new Map(
        input.calendars.map((calendar) => [calendarKey(calendar), calendar] as const),
      );
      const matched: CalendarRef[] = [];
      const unknown: string[] = [];
      for (const requested of input.requested) {
        const calendar = accessible.get(calendarKey(requested));
        if (calendar === undefined) {
          unknown.push(requested.mailbox);
          continue;
        }
        matched.push(calendar);
      }
      return {
        calendars: matched,
        notes:
          unknown.length === 0
            ? []
            : [
                `${unknown.length} requested calendar${unknown.length === 1 ? ' is' : 's are'} no longer accessible; call list_calendars again.`,
              ],
      };
    }
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
    userProfileId: string;
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
            hasMore: boolean;
            calendar: CalendarRef;
          }> => {
            try {
              const fetched = await this.fetchEvents({
                client: input.client,
                userProfileId: input.userProfileId,
                calendar,
                filters: input.filters,
                timeZone: input.timeZone,
                resolvedWindow: input.resolvedWindow,
              });
              return { ...fetched, calendar };
            } catch (error) {
              if (isDelegatedAccessNotAvailableError(error)) {
                logCalendarRecovered(this.logger, {
                  userProfileId: input.userProfileId,
                  mailbox: calendar.mailbox,
                  calendarId: calendar.calendarId,
                  ownerEmail: calendar.ownerEmail ?? undefined,
                  outcome: 'delegated_skipped',
                  msg: 'search_calendar_events skipped delegated calendar',
                  err: error,
                });
                return {
                  events: [],
                  notes: [
                    `Could not read calendar "${calendar.name}"${calendar.ownerEmail ? ` (${calendar.ownerEmail})` : ''}.`,
                  ],
                  fetched: 0,
                  hasMore: false,
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
    const incomplete = truncated || perCalendar.some((result) => result.hasMore);
    const totalFetched = perCalendar.reduce((sum, result) => sum + result.fetched, 0);
    const totalReturned = kept.length;
    this.logger.log({
      userProfileId: input.userProfileId,
      calendarCount: input.calendars.length,
      totalFetched,
      totalReturned,
      incomplete,
      msg: 'search_calendar_events Graph fan-out',
    });
    const notes = [
      ...calendarNotes,
      ...(kept.some(({ event, calendar }) => event.isPrivate && !calendar.canViewPrivateItems)
        ? ['Some events are marked private; details may be redacted.']
        : []),
      ...(incomplete
        ? [
            `Results are capped at ${MAX_EVENTS} events and more exist in this window. Narrow the date range or add filters.`,
          ]
        : []),
    ];
    if (totalReturned === 0) {
      this.logger.debug({
        userProfileId: input.userProfileId,
        calendarCount: input.calendars.length,
        totalFetched,
        msg: 'search_calendar_events no events matched',
      });
    }
    return { events: kept.map(({ event }) => event), notes };
  }

  @Span()
  private async fetchEvents(input: {
    client: Client;
    userProfileId: string;
    calendar: CalendarRef;
    filters: SearchCalendarEventsQueryInput;
    timeZone: string;
    resolvedWindow: ResolvedWindow;
  }): Promise<{ events: CalendarEvent[]; notes: string[]; fetched: number; hasMore: boolean }> {
    calendarTraceAttrs({
      userProfileId: input.userProfileId,
      mailbox: input.calendar.mailbox,
      calendarId: input.calendar.calendarId,
      operation: 'search_calendar_events.fetch',
    });
    const graphFilter = buildEventGraphFilter(input.filters);
    try {
      return await this.pageEvents({ ...input, graphFilter });
    } catch (error) {
      if (graphFilter === undefined || !isGraphBadRequestError(error)) {
        throw error;
      }
      // calendarView documents only "some of the OData query parameters", so a $filter it rejects
      // is a capability gap rather than a caller error. matchesFilters re-checks everything the
      // filter expressed, so re-reading the window unfiltered returns the same events.
      logCalendarRecovered(this.logger, {
        userProfileId: input.userProfileId,
        mailbox: input.calendar.mailbox,
        calendarId: input.calendar.calendarId,
        outcome: 'invalid',
        msg: 'search_calendar_events retried without $filter',
        err: error,
      });
      return this.pageEvents({ ...input, graphFilter: undefined });
    }
  }

  private async pageEvents(input: {
    client: Client;
    userProfileId: string;
    calendar: CalendarRef;
    filters: SearchCalendarEventsQueryInput;
    timeZone: string;
    resolvedWindow: ResolvedWindow;
    graphFilter: string | undefined;
  }): Promise<{ events: CalendarEvent[]; notes: string[]; fetched: number; hasMore: boolean }> {
    const mailbox = input.calendar.mailbox;
    const events: CalendarEvent[] = [];
    const prefer = `outlook.timezone="${input.timeZone}", outlook.body-content-type="text", IdType="ImmutableId"`;
    let nextPath: string | undefined = calendarViewPath({
      calendarId: input.calendar.calendarId,
      mailboxEmail: mailbox,
    });
    let isFirst = true;
    let pages = 0;
    let fetched = 0;

    while (nextPath !== undefined && pages < MAX_CALENDAR_VIEW_PAGES) {
      const request = input.client.api(nextPath).header('Prefer', prefer);
      const first = request
        .query({
          startDateTime: input.resolvedWindow.startDateTime,
          endDateTime: input.resolvedWindow.endDateTime,
        })
        .select(EVENT_SELECT)
        .orderby(EVENT_ORDER_BY)
        .top(CALENDAR_VIEW_TOP);
      const raw = isFirst
        ? await (input.graphFilter === undefined ? first : first.filter(input.graphFilter)).get()
        : await request.get();
      isFirst = false;
      pages += 1;
      const parsed = GraphEventCollectionSchema.parse(raw);
      for (const item of parsed.value) {
        fetched += 1;
        const event = mapGraphEventToCalendarEvent({
          event: item,
          calendar: input.calendar,
        });
        if (matchesFilters(event, input.filters)) {
          events.push(event);
        }
      }
      nextPath = parsed['@odata.nextLink'];
      if (events.length >= MAX_EVENTS) {
        // Ordered by start, so no later page can displace what is already held. If Graph ignored
        // $orderby the cap still holds — the result is then an arbitrary MAX_EVENTS of the window,
        // which is what hasMore reports.
        break;
      }
    }

    this.logger.debug({
      userProfileId: input.userProfileId,
      mailbox: obfuscateEmail(mailbox),
      calendarId: input.calendar.calendarId,
      pages,
      fetched,
      matched: events.length,
      msg: 'search_calendar_events calendar',
    });

    return { events, fetched, hasMore: nextPath !== undefined, notes: [] };
  }
}

function hasAttendeeFilter(input: SearchCalendarEventsQueryInput): boolean {
  return input.attendees !== undefined && input.attendees.length > 0;
}

function hasCategoryFilter(input: SearchCalendarEventsQueryInput): boolean {
  return input.categories !== undefined && input.categories.length > 0;
}

function matchesFilters(event: CalendarEvent, input: SearchCalendarEventsQueryInput): boolean {
  if (input.subject !== undefined && !matchesSubject(event.subject, input.subject)) {
    return false;
  }
  if (hasCategoryFilter(input) && !hasEvery(event.categories, input.categories ?? [])) {
    return false;
  }
  if (hasAttendeeFilter(input) && !hasEvery(attendeeAddresses(event), input.attendees ?? [])) {
    return false;
  }
  return true;
}

function matchesSubject(subject: string | null, filter: SubjectFilter): boolean {
  const haystack = (subject ?? '').toLowerCase();
  return 'startsWith' in filter
    ? haystack.startsWith(filter.startsWith.trim().toLowerCase())
    : haystack.includes(filter.contains.trim().toLowerCase());
}

/**
 * Narrowing a calendar means every named thing has to be on the event, not any of them. A caller
 * who wants either asks twice.
 */
function hasEvery(present: string[], wanted: string[]): boolean {
  const have = new Set(present.map((value) => value.toLowerCase()));
  return wanted.every((value) => have.has(value.trim().toLowerCase()));
}

/** The organizer counts as present: they are on the meeting whether or not Graph lists them. */
function attendeeAddresses(event: CalendarEvent): string[] {
  const addresses = event.attendees
    .map((attendee) => attendee.email)
    .filter((email): email is string => email !== null);
  return event.organizerEmail === null ? addresses : [...addresses, event.organizerEmail];
}

function calendarKey(calendar: { calendarId: string; mailbox: string }): string {
  return `${calendar.mailbox.toLowerCase()}\u0000${calendar.calendarId}`;
}
