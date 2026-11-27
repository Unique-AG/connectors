import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SearchCalendarEventsQuery } from '../search-calendar-events.query';
import {
  SearchCalendarEventsInputSchema,
  SearchCalendarEventsOutputSchema,
  SearchCalendarEventsTool,
} from '../search-calendar-events.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const CALENDARS = [{ calendarId: 'cal-own' }];

describe(SearchCalendarEventsTool.name, () => {
  it('passes a relative range through to the query', async () => {
    const output = {
      success: true,
      message: 'Found 1 event.',
      events: [],
      resolvedWindow: {
        startDateTime: '2026-08-25T00:00:00.000+02:00',
        endDateTime: '2026-08-25T23:59:59.999+02:00',
        timeZone: 'Europe/Zurich',
        serverCurrentDateTime: '2026-08-25T15:30:00.000+02:00',
        interpretation: 'today = Tue 2026-08-25 00:00 to Tue 2026-08-25 23:59 (Europe/Zurich)',
      },
    };
    const run = vi.fn().mockResolvedValue(output);
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    const result = await tool.searchCalendarEvents(
      {
        calendars: CALENDARS,
        dateRange: { rangeType: 'relative', range: 'today' },
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      calendars: CALENDARS,
      range: 'today',
    });
    expect(SearchCalendarEventsOutputSchema.parse(result)).toEqual(output);
  });

  it('passes the subject and attendee filters through unchanged', async () => {
    const run = vi.fn().mockResolvedValue({ success: true, message: 'ok', events: [] });
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    await tool.searchCalendarEvents(
      {
        calendars: CALENDARS,
        dateRange: { rangeType: 'relative', range: 'thisWeek' },
        subject: { startsWith: 'Weekly' },
        attendees: ['alex@example.com', 'pat@example.com'],
        categories: ['Client', 'Urgent'],
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      calendars: CALENDARS,
      subject: { startsWith: 'Weekly' },
      attendees: ['alex@example.com', 'pat@example.com'],
      categories: ['Client', 'Urgent'],
      range: 'thisWeek',
    });
  });

  it('passes an absolute window through to the query', async () => {
    const run = vi.fn().mockResolvedValue({
      success: true,
      message: 'No events matched the search.',
      events: [],
    });
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    await tool.searchCalendarEvents(
      {
        calendars: CALENDARS,
        dateRange: {
          rangeType: 'absolute',
          startDateTime: '2026-08-25T00:00:00+02:00',
          endDateTime: '2026-08-26T00:00:00+02:00',
        },
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      calendars: CALENDARS,
      startDateTime: '2026-08-25T00:00:00+02:00',
      endDateTime: '2026-08-26T00:00:00+02:00',
    });
  });

  it('titles each event by its subject or "(no subject)"', async () => {
    const webLink =
      'https://outlook.office365.com/owa/?itemid=AAMkEvent1&exvsurl=1&path=/calendar/item';
    const event = (overrides: Record<string, unknown>) => ({
      subject: 'Quarterly review',
      body: 'Agenda',
      bodyTruncated: false,
      start: { dateTime: '2026-08-25T10:00:00.0000000', timeZone: 'Europe/Zurich' },
      end: { dateTime: '2026-08-25T11:00:00.0000000', timeZone: 'Europe/Zurich' },
      location: null,
      joinUrl: 'https://teams.microsoft.com/l/meetup-join/abc',
      attendees: [
        { name: 'Alex', email: 'alex@example.com', response: 'accepted', type: 'required' },
      ],
      organizerName: 'Alex',
      organizerEmail: 'alex@example.com',
      isCancelled: false,
      isAllDay: false,
      isPrivate: false,
      sensitivity: 'normal',
      categories: [],
      recurrence: null,
      seriesMasterId: null,
      type: 'singleInstance',
      showAs: 'busy',
      webLink,
      calendarName: 'Calendar',
      ownerEmail: 'own@example.com',
      ownerName: 'Own',
      isOwn: true,
      eventRef: { eventId: 'event-1', calendarId: 'cal-own' },
      ...overrides,
    });
    const linked = event({});
    const redacted = event({
      subject: null,
      webLink: null,
      eventRef: { eventId: 'event-2', calendarId: 'cal-own' },
    });
    const output = {
      success: true,
      message: 'Found 2 events.',
      events: [linked, redacted],
      searchNotes: ['Results were capped.'],
    };
    const tool = new SearchCalendarEventsTool({
      run: vi.fn().mockResolvedValue(output),
    } as unknown as SearchCalendarEventsQuery);

    const result = await tool.searchCalendarEvents(
      { calendars: CALENDARS, dateRange: { rangeType: 'relative', range: 'today' } },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(result).toEqual({
      success: true,
      message: 'Found 2 events.',
      searchNotes: ['Results were capped.'],
      events: [
        { ...linked, title: 'Quarterly review' },
        { ...redacted, title: '(no subject)' },
      ],
    });
  });
});

describe('SearchCalendarEventsInputSchema', () => {
  it('rejects a subject filter that sets both startsWith and contains', () => {
    expect(() =>
      SearchCalendarEventsInputSchema.parse({
        calendars: CALENDARS,
        dateRange: { rangeType: 'relative', range: 'today' },
        subject: { startsWith: 'Weekly', contains: 'Sales' },
      }),
    ).toThrow();
  });

  it('rejects an attendee that is not an SMTP address', () => {
    expect(() =>
      SearchCalendarEventsInputSchema.parse({
        calendars: CALENDARS,
        dateRange: { rangeType: 'relative', range: 'today' },
        attendees: ['Alex'],
      }),
    ).toThrow(/SMTP/i);
  });

  it('rejects a relative search without range', () => {
    expect(() =>
      SearchCalendarEventsInputSchema.parse({
        calendars: CALENDARS,
        dateRange: { rangeType: 'relative' },
      }),
    ).toThrow(/range/i);
  });

  it('rejects an absolute search without a window', () => {
    expect(() =>
      SearchCalendarEventsInputSchema.parse({
        calendars: CALENDARS,
        dateRange: { rangeType: 'absolute' },
      }),
    ).toThrow(/startDateTime|endDateTime/i);
  });

  it('rejects an absolute window without a timezone offset', () => {
    expect(() =>
      SearchCalendarEventsInputSchema.parse({
        calendars: CALENDARS,
        dateRange: {
          rangeType: 'absolute',
          startDateTime: '2026-08-25T00:00:00',
          endDateTime: '2026-08-26T00:00:00+02:00',
        },
      }),
    ).toThrow(/offset/i);
  });

  it('rejects a search without calendars', () => {
    expect(() =>
      SearchCalendarEventsInputSchema.parse({
        dateRange: { rangeType: 'relative', range: 'today' },
      }),
    ).toThrow(/calendars/i);
  });
});
