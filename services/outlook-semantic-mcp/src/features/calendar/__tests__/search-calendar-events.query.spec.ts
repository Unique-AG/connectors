import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import type { CalendarRef } from '../calendar.schemas';
import { SearchCalendarEventsQuery } from '../search-calendar-events.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const OWNER_EMAIL = 'banker@example.com';
const WINDOW = {
  startDateTime: '2026-08-25T00:00:00+02:00',
  endDateTime: '2026-08-26T00:00:00+02:00',
};
const EVENT_SELECT =
  'id,subject,body,start,end,location,attendees,organizer,isOnlineMeeting,onlineMeeting,onlineMeetingUrl,webLink,isCancelled,isAllDay,sensitivity,categories,type,seriesMasterId,recurrence,showAs';
const PREFER =
  'outlook.timezone="W. Europe Standard Time", outlook.body-content-type="text", IdType="ImmutableId"';

const OWN_CALENDAR: CalendarRef = {
  calendarId: 'cal-own',
  name: 'Calendar',
  ownerEmail: OWN_EMAIL,
  ownerName: 'Me',
  isOwn: true,
  canEdit: true,
  canViewPrivateItems: true,
  accessPath: 'ownMailbox',
};

const DELEGATED_CALENDAR: CalendarRef = {
  calendarId: 'cal-banker',
  name: 'Banker',
  ownerEmail: OWNER_EMAIL,
  ownerName: 'Banker',
  isOwn: false,
  canEdit: true,
  canViewPrivateItems: false,
  accessPath: 'ownerMailbox',
};

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
  timeZone?: string | null;
  get?: ReturnType<typeof vi.fn>;
  getByPath?: Record<string, unknown | Error>;
}) {
  const get = opts.get ?? vi.fn().mockResolvedValue({ value: [] });
  const request = {
    header: vi.fn().mockReturnThis(),
    query: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    top: vi.fn().mockReturnThis(),
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
            query: vi.fn().mockReturnThis(),
            select: vi.fn().mockReturnThis(),
            top: vi.fn().mockReturnThis(),
            get: pathGet,
          };
        });
  const query = new SearchCalendarEventsQuery(
    {
      run: vi
        .fn()
        .mockImplementation(async ({ fn }) =>
          fn({ client: { api }, clientUserProfileId: 'client-1' }),
        ),
    } as never,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: OWN_EMAIL,
        source: 'oauth',
      }),
    } as never,
    {
      run: vi.fn().mockResolvedValue(
        opts.listResult ?? {
          success: true,
          message: 'Found calendars.',
          calendars: opts.calendars ?? [OWN_CALENDAR],
        },
      ),
    } as never,
    {
      run: vi
        .fn()
        .mockResolvedValue(
          opts.timeZone === null ? undefined : (opts.timeZone ?? 'W. Europe Standard Time'),
        ),
    } as never,
  );

  return { query, api, request };
}

describe(SearchCalendarEventsQuery.name, () => {
  it('queries calendarView with Prefer headers and returns a mapped event', async () => {
    const { query, api, request } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [graphEvent()] }),
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(api).toHaveBeenCalledWith('/me/calendars/cal-own/calendarView');
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
          accessPath: 'ownMailbox',
          mailbox: OWN_EMAIL,
        },
      }),
    ]);
    expect(result.events?.[0]?.attendees).toEqual([
      { name: 'Alex', email: 'alex@example.com', response: 'accepted', type: 'required' },
    ]);
  });

  it('keeps other calendars and records a note when one calendarView returns 403', async () => {
    const { query } = createQuery({
      calendars: [OWN_CALENDAR, DELEGATED_CALENDAR],
      getByPath: {
        '/me/calendars/cal-own/calendarView': { value: [graphEvent()] },
        [`/users/${OWNER_EMAIL}/calendars/cal-banker/calendarView`]: makeGraphError(
          403,
          'ErrorAccessDenied',
        ),
      },
    });

    const result = await query.run(USER_PROFILE_ID, WINDOW);

    expect(result.success).toBe(true);
    expect(result.events).toHaveLength(1);
    expect(result.searchNotes).toEqual([`Could not read calendar "Banker" (${OWNER_EMAIL}).`]);
  });

  it('filters attendees in-process', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          graphEvent({ id: 'keep' }),
          graphEvent({
            id: 'drop',
            subject: 'Other',
            attendees: [
              {
                emailAddress: { name: 'Pat', address: 'pat@example.com' },
                status: { response: 'none' },
              },
            ],
          }),
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, { ...WINDOW, attendee: 'alex@' });

    expect(result.events?.map((event) => event.eventRef.eventId)).toEqual(['keep']);
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
      timeZone: null,
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
        [`/users/${OWNER_EMAIL}/calendars/cal-banker/calendarView`]: {
          value: [graphEvent({ id: 'banker-evt' })],
        },
      },
    });

    const result = await query.run(USER_PROFILE_ID, { ...WINDOW, mailbox: OWNER_EMAIL });

    expect(api).toHaveBeenCalledWith(`/users/${OWNER_EMAIL}/calendars/cal-banker/calendarView`);
    expect(api).not.toHaveBeenCalledWith('/me/calendars/cal-own/calendarView');
    expect(result.events?.[0]?.eventRef).toEqual({
      eventId: 'banker-evt',
      calendarId: 'cal-banker',
      accessPath: 'ownerMailbox',
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

    const result = await query.run(USER_PROFILE_ID, { range: 'today' }, now);

    expect(request.query).toHaveBeenCalledWith({
      startDateTime: '2026-08-25T00:00:00.000+02:00',
      endDateTime: '2026-08-25T23:59:59.999+02:00',
    });
    expect(result.resolvedWindow?.interpretation).toContain('today = Tue 2026-08-25 00:00');
  });
});
