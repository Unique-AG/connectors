import { GraphError } from '@microsoft/microsoft-graph-client';
import { Temporal } from 'temporal-polyfill';
import { describe, expect, it, vi } from 'vitest';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import {
  type ResolvedMailboxTimezone,
  ResolveMailboxTimezoneQuery,
} from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import type { CalendarRef } from '../calendar.schemas';
import { ListCalendarsQuery } from '../list-calendars.query';
import { SearchCalendarEventsQuery } from '../search-calendar-events.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const OWNER_EMAIL = 'banker@example.com';
const OWN_VIEW = `/users/${OWN_EMAIL}/calendars/cal-own/calendarView`;
const OWNER_VIEW = `/users/${OWNER_EMAIL}/calendars/cal-banker/calendarView`;
const WINDOW = {
  startDateTime: '2026-08-25T00:00:00+02:00',
  endDateTime: '2026-08-26T00:00:00+02:00',
};
const EVENT_SELECT =
  'id,subject,body,start,end,location,attendees,organizer,onlineMeeting,onlineMeetingUrl,webLink,isCancelled,isAllDay,sensitivity,categories,type,seriesMasterId,recurrence,showAs';
const PREFER =
  'outlook.timezone="W. Europe Standard Time", outlook.body-content-type="text", IdType="ImmutableId"';
const DEFAULT_TIMEZONE: ResolvedMailboxTimezone = {
  ianaTimeZone: 'Europe/Zurich',
  outlookTimeZone: 'W. Europe Standard Time',
  notes: [],
};
const UNMAPPED_TIMEZONE: ResolvedMailboxTimezone = {
  ianaTimeZone: 'UTC',
  outlookTimeZone: 'UTC',
  notes: [
    'Mailbox timezone "Not A Real Zone" could not be mapped to IANA; relative windows are resolved in UTC.',
  ],
};
const MISSING_TIMEZONE: ResolvedMailboxTimezone = {
  ianaTimeZone: 'UTC',
  outlookTimeZone: 'UTC',
  notes: ['Mailbox timezone was unavailable; times are requested in UTC.'],
};

const OWN_CALENDAR: CalendarRef = {
  calendarId: 'cal-own',
  name: 'Calendar',
  mailbox: OWN_EMAIL,
  ownerEmail: OWN_EMAIL,
  ownerName: 'Me',
  isOwn: true,
  canEdit: true,
  canViewPrivateItems: true,
};

const DELEGATED_CALENDAR: CalendarRef = {
  calendarId: 'cal-banker',
  name: 'Banker',
  mailbox: OWNER_EMAIL,
  ownerEmail: OWNER_EMAIL,
  ownerName: 'Banker',
  isOwn: false,
  canEdit: true,
  canViewPrivateItems: false,
};

const SHARED_INTO_OWN_MAILBOX: CalendarRef = {
  calendarId: 'cal-shared',
  name: 'Banker',
  mailbox: OWN_EMAIL,
  ownerEmail: OWNER_EMAIL,
  ownerName: 'Banker',
  isOwn: false,
  canEdit: false,
  canViewPrivateItems: false,
};
const SHARED_VIEW = `/users/${OWN_EMAIL}/calendars/cal-shared/calendarView`;

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

function graphEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: 'evt-1',
    subject: 'Standup',
    body: { content: 'Agenda', contentType: 'text' },
    start: { dateTime: '2026-08-25T09:00:00.0000000', timeZone: 'W. Europe Standard Time' },
    end: { dateTime: '2026-08-25T09:30:00.0000000', timeZone: 'W. Europe Standard Time' },
    location: { displayName: 'Room A' },
    attendees: [
      {
        type: 'required',
        status: { response: 'accepted' },
        emailAddress: { name: 'Alex', address: 'alex@example.com' },
      },
    ],
    organizer: { emailAddress: { name: 'Me', address: OWN_EMAIL } },
    isOnlineMeeting: true,
    onlineMeeting: { joinUrl: 'https://teams.example/join' },
    webLink: 'https://outlook.example/evt-1',
    isCancelled: false,
    isAllDay: false,
    sensitivity: 'normal',
    categories: ['Work'],
    type: 'singleInstance',
    showAs: 'busy',
    ...overrides,
  };
}

function createQuery(opts: {
  calendars?: CalendarRef[];
  listResult?: {
    success: boolean;
    message: string;
    consentRequired?: boolean;
    calendars?: CalendarRef[];
  };
  timezone?: ResolvedMailboxTimezone;
  get?: ReturnType<typeof vi.fn>;
  getByPath?: Record<string, unknown | Error>;
}) {
  const get = opts.get ?? vi.fn().mockResolvedValue({ value: [] });
  const measureSearch = vi.fn((_filters: unknown, fn: () => Promise<unknown>) => fn());
  const queryCalls: unknown[] = [];
  const filterCalls: string[] = [];
  const orderbyCalls: (string | string[])[] = [];
  const request = {
    header: vi.fn().mockReturnThis(),
    query: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    top: vi.fn().mockReturnThis(),
    orderby: vi.fn().mockImplementation(function (this: object, value: string) {
      orderbyCalls.push(value);
      return this;
    }),
    filter: vi.fn().mockImplementation(function (this: object, value: string) {
      filterCalls.push(value);
      return this;
    }),
    get,
  };
  const api =
    opts.getByPath === undefined
      ? vi.fn().mockReturnValue(request)
      : vi.fn().mockImplementation((path: string) => {
          const response = opts.getByPath?.[path];
          const pathGet =
            response instanceof Error
              ? vi.fn().mockRejectedValue(response)
              : vi.fn().mockResolvedValue(response ?? { value: [] });
          return {
            header: vi.fn().mockReturnThis(),
            query: vi.fn().mockImplementation(function (this: object, args: unknown) {
              queryCalls.push(args);
              return this;
            }),
            select: vi.fn().mockReturnThis(),
            top: vi.fn().mockReturnThis(),
            orderby: vi.fn().mockReturnThis(),
            filter: vi.fn().mockImplementation(function (this: object, value: string) {
              filterCalls.push(value);
              return this;
            }),
            get: pathGet,
          };
        });
  const query = new SearchCalendarEventsQuery(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as unknown as GraphClientFactory,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: OWN_EMAIL,
        source: 'oauth',
      }),
    } as unknown as GetUserProfileQuery,
    {
      run: vi.fn().mockResolvedValue(
        opts.listResult ?? {
          success: true,
          message: 'Found calendars.',
          calendars: opts.calendars ?? [OWN_CALENDAR],
        },
      ),
    } as unknown as ListCalendarsQuery,
    {
      run: vi.fn().mockResolvedValue(opts.timezone ?? DEFAULT_TIMEZONE),
    } as unknown as ResolveMailboxTimezoneQuery,
    { measureSearch } as unknown as CalendarMetricsService,
  );

  return { query, api, request, measureSearch, queryCalls, filterCalls, orderbyCalls };
}

describe(SearchCalendarEventsQuery.name, () => {
  it('queries calendarView with Prefer headers and returns a mapped event', async () => {
    const { query, api, request } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [graphEvent()] }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(api).toHaveBeenCalledWith(OWN_VIEW);
    expect(request.header).toHaveBeenCalledWith('Prefer', PREFER);
    expect(request.query).toHaveBeenCalledWith(WINDOW);
    expect(request.select).toHaveBeenCalledWith(EVENT_SELECT);
    expect(result.success).toBe(true);
    expect(result.resolvedWindow?.startDateTime).toBe(WINDOW.startDateTime);
    expect(result.events).toEqual([
      expect.objectContaining({
        subject: 'Standup',
        body: 'Agenda',
        bodyTruncated: false,
        location: 'Room A',
        joinUrl: 'https://teams.example/join',
        isCancelled: false,
        isPrivate: false,
        calendarName: 'Calendar',
        eventRef: {
          eventId: 'evt-1',
          calendarId: 'cal-own',
          mailbox: OWN_EMAIL,
        },
      }),
    ]);
    expect(result.events?.[0]?.attendees).toEqual([
      { name: 'Alex', email: 'alex@example.com', response: 'accepted', type: 'required' },
    ]);
  });

  it('matches an attendee address against the organizer when Graph omitted them from attendees', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          graphEvent({
            id: 'keep',
            attendees: [],
            organizer: { emailAddress: { name: 'Jordan Lee', address: 'jordan@example.com' } },
          }),
          graphEvent({
            id: 'drop',
            attendees: [],
            organizer: { emailAddress: { name: 'Pat', address: 'pat@example.com' } },
          }),
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      attendees: ['JORDAN@example.com'],
    });

    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['keep']);
  });

  it('requires every requested attendee address to be on the event', async () => {
    const both = graphEvent({
      id: 'both',
      attendees: [
        { emailAddress: { address: 'alex@example.com' }, status: { response: 'accepted' } },
        { emailAddress: { address: 'pat@example.com' }, status: { response: 'accepted' } },
      ],
    });
    const onlyOne = graphEvent({
      id: 'only-one',
      attendees: [{ emailAddress: { address: 'alex@example.com' }, status: { response: 'none' } }],
    });
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [both, onlyOne] }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      attendees: ['alex@example.com', 'pat@example.com'],
    });

    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['both']);
  });

  it('does not match an attendee on a partial address', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [graphEvent()] }),
    });

    const result = await query.run(USER_PROFILE_ID, { ...WINDOW, attendees: ['alex@example.co'] });

    expect(result.events).toEqual([]);
  });

  it('sends the category filter to Graph and re-checks it in-process', async () => {
    const { query, filterCalls } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          graphEvent({ id: 'keep', categories: ['Client'] }),
          graphEvent({ id: 'drop', categories: ['Work'] }),
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, { ...WINDOW, categories: ['client'] });

    expect(filterCalls).toEqual(["categories/any(c:c eq 'client')"]);
    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['keep']);
  });

  it('requires every requested category to be on the event', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          graphEvent({ id: 'both', categories: ['Client', 'Urgent'] }),
          graphEvent({ id: 'only-one', categories: ['Client'] }),
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      categories: ['client', 'URGENT'],
    });

    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['both']);
  });

  it('sends subject startsWith to Graph and combines it with the category filter', async () => {
    const { query, filterCalls, orderbyCalls } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [graphEvent({ categories: ['Client'] })] }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      categories: ["O'Brien"],
      subject: { startsWith: 'Stand' },
    });

    expect(filterCalls).toEqual([
      "categories/any(c:c eq 'O''Brien') and startswith(subject,'Stand')",
    ]);
    expect(orderbyCalls).toEqual(['start/dateTime']);
    expect(result.success).toBe(true);
  });

  it('keeps subject contains out of the Graph request and matches it case-insensitively', async () => {
    const { query, filterCalls } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          graphEvent({ id: 'keep', subject: 'Weekly STANDUP sync' }),
          graphEvent({ id: 'drop', subject: 'Retro' }),
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      subject: { contains: 'standup' },
    });

    expect(filterCalls).toEqual([]);
    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['keep']);
  });

  it('matches subject startsWith case-insensitively in-process', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          graphEvent({ id: 'keep', subject: 'STANDUP with Alex' }),
          graphEvent({ id: 'drop', subject: 'Alex standup' }),
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      subject: { startsWith: 'standup' },
    });

    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['keep']);
  });

  it('retries the calendar without $filter when Graph rejects it, keeping in-process filtering', async () => {
    const get = vi
      .fn()
      .mockRejectedValueOnce(makeGraphError(400, 'ErrorInvalidUrlQueryFilter'))
      .mockResolvedValueOnce({
        value: [
          graphEvent({ id: 'keep', categories: ['Client'] }),
          graphEvent({ id: 'drop', categories: ['Work'] }),
        ],
      });
    const { query, filterCalls } = createQuery({ get });

    const result = await query.run(USER_PROFILE_ID, { ...WINDOW, categories: ['Client'] });

    expect(filterCalls).toEqual(["categories/any(c:c eq 'Client')"]);
    expect(result.success).toBe(true);
    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['keep']);
  });

  it('returns cancelled occurrences flagged rather than dropping them', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [graphEvent({ id: 'called-off', isCancelled: true })],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(result.events).toHaveLength(1);
    expect(result.events?.[0]?.isCancelled).toBe(true);
  });

  it('notes private events on calendars that cannot show private details', async () => {
    const { query } = createQuery({
      calendars: [DELEGATED_CALENDAR],
      get: vi.fn().mockResolvedValue({
        value: [graphEvent({ id: 'secret', sensitivity: 'private', subject: null })],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(result.events?.[0]?.isPrivate).toBe(true);
    expect(result.events?.[0]?.sensitivity).toBe('private');
    expect(result.searchNotes).toContain(
      'Some events are marked private; details may be redacted.',
    );
  });

  it('notes when the mailbox timezone cannot be mapped to IANA', async () => {
    const { query, request } = createQuery({
      timezone: UNMAPPED_TIMEZONE,
      get: vi.fn().mockResolvedValue({ value: [] }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(request.header).toHaveBeenCalledWith(
      'Prefer',
      'outlook.timezone="UTC", outlook.body-content-type="text", IdType="ImmutableId"',
    );
    expect(result.resolvedWindow?.timeZone).toBe('UTC');
    expect(result.searchNotes).toContain(
      'Mailbox timezone "Not A Real Zone" could not be mapped to IANA; relative windows are resolved in UTC.',
    );
  });

  it('stops paging once the event cap is reached instead of draining nextLink', async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => graphEvent({ id: `p1-${index}` }));
    const get = vi.fn().mockResolvedValue({
      value: firstPage,
      '@odata.nextLink':
        'https://graph.microsoft.com/v1.0/users/me/calendars/cal-own/calendarView?$skiptoken=1',
    });
    const { query } = createQuery({ get });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(get).toHaveBeenCalledTimes(1);
    expect(result.events).toHaveLength(100);
    expect(result.searchNotes).toContain(
      'Results are capped at 100 events and more exist in this window. Narrow the date range or add filters.',
    );
  });

  it('follows nextLink while under the cap and reports when the page limit is hit', async () => {
    const page = Array.from({ length: 10 }, (_, index) => graphEvent({ id: `e-${index}` }));
    const get = vi.fn().mockResolvedValue({
      value: page,
      '@odata.nextLink':
        'https://graph.microsoft.com/v1.0/users/me/calendars/cal-own/calendarView?$skiptoken=1',
    });
    const { query } = createQuery({ get });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(get).toHaveBeenCalledTimes(5);
    expect(result.events).toHaveLength(50);
    expect(result.searchNotes).toContain(
      'Results are capped at 100 events and more exist in this window. Narrow the date range or add filters.',
    );
  });

  it('reports no cap note when the window fits', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [graphEvent()] }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(result.searchNotes).toBeUndefined();
  });

  it('accepts Graph events whose optional objects are null', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          graphEvent({
            id: 'sparse',
            body: null,
            location: null,
            attendees: null,
            organizer: null,
            onlineMeeting: null,
            categories: null,
            recurrence: null,
          }),
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(result.success).toBe(true);
    expect(result.events?.[0]?.eventRef.eventId).toBe('sparse');
    expect(result.events?.[0]?.body).toBe('');
    expect(result.events?.[0]?.location).toBeNull();
  });

  it('records in-memory filter flags on the search metric', async () => {
    const { query, measureSearch } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [] }),
    });

    await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      attendees: ['alex@example.com'],
      subject: { contains: 'Standup' },
    });

    expect(measureSearch).toHaveBeenCalledWith(
      {
        dateWindow: '<1week',
        hasAttendeeFilter: true,
        hasSubjectFilter: true,
        hasCategoryFilter: false,
      },
      expect.any(Function),
    );
  });

  it.each([
    ['403', makeGraphError(403, 'ErrorAccessDenied')],
    ['404', makeGraphError(404, 'ErrorItemNotFound')],
  ])('keeps other calendars and records a note when one calendarView returns %s', async (_label, error) => {
    const { query } = createQuery({
      calendars: [OWN_CALENDAR, DELEGATED_CALENDAR],
      getByPath: {
        [OWN_VIEW]: { value: [graphEvent()] },
        [OWNER_VIEW]: error,
      },
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(result.success).toBe(true);
    expect(result.events).toHaveLength(1);
    expect(result.searchNotes).toEqual([`Could not read calendar "Banker" (${OWNER_EMAIL}).`]);
  });

  it('passes through consentRequired from list_calendars', async () => {
    const { query } = createQuery({
      listResult: {
        success: false,
        message: 'Reconnect Outlook',
        consentRequired: true,
      },
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(result).toEqual({
      success: false,
      message: 'Reconnect Outlook',
      consentRequired: true,
    });
  });

  it('notes UTC fallback when mailbox timezone is missing', async () => {
    const { query, request } = createQuery({
      timezone: MISSING_TIMEZONE,
      get: vi.fn().mockResolvedValue({ value: [] }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(request.header).toHaveBeenCalledWith(
      'Prefer',
      'outlook.timezone="UTC", outlook.body-content-type="text", IdType="ImmutableId"',
    );
    expect(result.resolvedWindow?.timeZone).toBe('UTC');
    expect(result.searchNotes).toContain(
      'Mailbox timezone was unavailable; times are requested in UTC.',
    );
  });

  it('scopes to calendars whose owner matches mailbox', async () => {
    const { query, api } = createQuery({
      calendars: [OWN_CALENDAR, DELEGATED_CALENDAR],
      getByPath: {
        [OWNER_VIEW]: {
          value: [graphEvent({ id: 'banker-evt' })],
        },
      },
    });

    const result = await query.run(USER_PROFILE_ID, { ...WINDOW, mailbox: OWNER_EMAIL });

    expect(api).toHaveBeenCalledWith(OWNER_VIEW);
    expect(api).not.toHaveBeenCalledWith(OWN_VIEW);
    expect(result.events?.[0]?.eventRef).toEqual({
      eventId: 'banker-evt',
      calendarId: 'cal-banker',
      mailbox: OWNER_EMAIL,
    });
  });

  it('sorts events by start and flags a truncated body', async () => {
    const longBody = 'x'.repeat(4001);
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          graphEvent({
            id: 'later',
            start: { dateTime: '2026-08-25T11:00:00.0000000' },
          }),
          graphEvent({
            id: 'earlier',
            start: { dateTime: '2026-08-25T08:00:00.0000000' },
            body: { content: longBody, contentType: 'text' },
          }),
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['earlier', 'later']);
    expect(result.events?.[0]?.bodyTruncated).toBe(true);
    expect(result.events?.[0]?.body).toHaveLength(4000);
  });

  it('resolves a relative range in the mailbox timezone', async () => {
    const { query, request } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [] }),
    });
    const now = Temporal.ZonedDateTime.from('2026-08-25T15:30:00[Europe/Zurich]');

    const result = await query.run(USER_PROFILE_ID, { range: 'today', now });

    expect(request.query).toHaveBeenCalledWith({
      startDateTime: '2026-08-25T00:00:00.000+02:00',
      endDateTime: '2026-08-25T23:59:59.999+02:00',
    });
    expect(result.resolvedWindow?.interpretation).toContain('today = Tue 2026-08-25 00:00');
  });

  it('reads a calendar shared into the caller mailbox from the caller mailbox', async () => {
    // Regression: classifying this as the owner's calendar sent the caller-namespace id to
    // /users/{owner}/... , which live Graph answers with 404 ErrorItemNotFound.
    const { query, api } = createQuery({
      calendars: [SHARED_INTO_OWN_MAILBOX],
      getByPath: { [SHARED_VIEW]: { value: [graphEvent({ id: 'shared-evt' })] } },
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(api).toHaveBeenCalledWith(SHARED_VIEW);
    expect(api).not.toHaveBeenCalledWith(`/users/${OWNER_EMAIL}/calendars/cal-shared/calendarView`);
    expect(result.events?.[0]?.eventRef).toEqual({
      eventId: 'shared-evt',
      calendarId: 'cal-shared',
      mailbox: OWN_EMAIL,
    });
  });

  it('narrows the fan-out to the requested calendars', async () => {
    const { query, api } = createQuery({
      calendars: [OWN_CALENDAR, DELEGATED_CALENDAR],
      getByPath: { [OWNER_VIEW]: { value: [graphEvent({ id: 'banker-evt' })] } },
    });

    const result = await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      calendars: [{ calendarId: 'cal-banker', mailbox: OWNER_EMAIL }],
    });

    expect(api).toHaveBeenCalledWith(OWNER_VIEW);
    expect(api).not.toHaveBeenCalledWith(OWN_VIEW);
    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['banker-evt']);
  });

  it('notes a requested calendar that is no longer accessible instead of calling Graph', async () => {
    const { query, api } = createQuery({ calendars: [OWN_CALENDAR] });

    const result = await query.run(USER_PROFILE_ID, {
      ...WINDOW,
      calendars: [{ calendarId: 'cal-gone', mailbox: OWNER_EMAIL }],
    });

    expect(api).not.toHaveBeenCalled();
    expect(result.success).toBe(true);
    expect(result.events).toEqual([]);
    expect(result.searchNotes?.join(' ')).toMatch(/no longer accessible/i);
  });

  it('sends one identical window to every calendar in the fan-out', async () => {
    const { query, queryCalls } = createQuery({
      calendars: [OWN_CALENDAR, DELEGATED_CALENDAR, SHARED_INTO_OWN_MAILBOX],
      getByPath: {
        [OWN_VIEW]: { value: [] },
        [OWNER_VIEW]: { value: [] },
        [SHARED_VIEW]: { value: [] },
      },
    });

    // A relative range resolved per calendar could straddle midnight and produce different days.
    const now = Temporal.ZonedDateTime.from('2026-08-25T23:59:59.999[Europe/Zurich]');
    const result = await query.run(USER_PROFILE_ID, { range: 'today', now });

    const expected = {
      startDateTime: result.resolvedWindow?.startDateTime,
      endDateTime: result.resolvedWindow?.endDateTime,
    };
    expect(queryCalls).toEqual([expected, expected, expected]);
  });
});
