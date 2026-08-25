import { GraphError } from '@microsoft/microsoft-graph-client';
import { Temporal } from 'temporal-polyfill';
import { describe, expect, it, vi } from 'vitest';
import type { ResolvedMailboxTimezone } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CheckAvailabilityQuery } from '../check-availability.query';
import { passthroughCalendarMetrics } from './passthrough-calendar-metrics';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const ATTENDEE = 'alex@example.com';
const SCHEDULE_PATH = `/users/${OWN_EMAIL}/calendar/getSchedule`;
const OWNER_PATH = '/users/banker@example.com/calendar/getSchedule';
const PREFER = 'outlook.timezone="W. Europe Standard Time"';
const NOW = Temporal.ZonedDateTime.from('2026-08-25T15:30:00+02:00[Europe/Zurich]');
const DEFAULT_TIMEZONE: ResolvedMailboxTimezone = {
  ianaTimeZone: 'Europe/Zurich',
  outlookTimeZone: 'W. Europe Standard Time',
  notes: [],
};
const UNMAPPED_TIMEZONE: ResolvedMailboxTimezone = {
  ianaTimeZone: 'UTC',
  outlookTimeZone: 'UTC',
  notes: [
    'Mailbox timezone "Customized Time Zone" could not be mapped to IANA; relative windows are resolved in UTC.',
  ],
};

function makeGraphError(statusCode: number, code: string, message = 'Access denied'): GraphError {
  const err = new GraphError(statusCode, message);
  err.code = code;
  return err;
}

function createQuery(
  opts: {
    post?: ReturnType<typeof vi.fn>;
    email?: string;
    timezone?: ResolvedMailboxTimezone;
  } = {},
) {
  const post = opts.post ?? vi.fn().mockResolvedValue({ value: [] });
  const request = {
    header: vi.fn().mockReturnThis(),
    post,
  };
  const api = vi.fn().mockReturnValue(request);
  const query = new CheckAvailabilityQuery(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as never,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: opts.email ?? OWN_EMAIL,
        source: 'oauth',
      }),
    } as never,
    {
      run: vi.fn().mockResolvedValue(opts.timezone ?? DEFAULT_TIMEZONE),
    } as never,
    passthroughCalendarMetrics() as never,
  );
  return { query, api, request, post };
}

describe(CheckAvailabilityQuery.name, () => {
  it('POSTs getSchedule on /users/{email}/calendar and decodes busy blocks', async () => {
    const { query, api, request, post } = createQuery({
      post: vi.fn().mockResolvedValue({
        value: [
          {
            scheduleId: ATTENDEE,
            availabilityView: '000220130',
            scheduleItems: [
              {
                isPrivate: false,
                status: 'busy',
                subject: 'Lunch',
                location: "Harry's Bar",
                start: {
                  dateTime: '2026-08-25T12:00:00.0000000',
                  timeZone: 'W. Europe Standard Time',
                },
                end: {
                  dateTime: '2026-08-25T14:00:00.0000000',
                  timeZone: 'W. Europe Standard Time',
                },
              },
              {
                isPrivate: true,
                status: 'busy',
                subject: 'Secret',
                location: 'Home',
                start: {
                  dateTime: '2026-08-25T16:00:00.0000000',
                  timeZone: 'W. Europe Standard Time',
                },
                end: {
                  dateTime: '2026-08-25T17:00:00.0000000',
                  timeZone: 'W. Europe Standard Time',
                },
              },
            ],
            workingHours: {
              daysOfWeek: ['monday', 'tuesday'],
              startTime: '08:00:00.0000000',
              endTime: '17:00:00.0000000',
              timeZone: { name: 'W. Europe Standard Time' },
            },
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      startDateTime: '2026-08-25T09:00:00+02:00',
      endDateTime: '2026-08-25T18:00:00+02:00',
      intervalMinutes: 60,
      now: NOW,
    });

    expect(api).toHaveBeenCalledWith(SCHEDULE_PATH);
    expect(request.header).toHaveBeenCalledWith('Prefer', PREFER);
    expect(post).toHaveBeenCalledWith({
      schedules: [ATTENDEE],
      startTime: { dateTime: '2026-08-25T09:00:00', timeZone: 'W. Europe Standard Time' },
      endTime: { dateTime: '2026-08-25T18:00:00', timeZone: 'W. Europe Standard Time' },
      availabilityViewInterval: 60,
    });
    expect(result.success).toBe(true);
    expect(result.people).toEqual([
      {
        email: ATTENDEE,
        busyBlocks: [
          {
            status: 'busy',
            startDateTime: '2026-08-25T12:00:00.000+02:00',
            endDateTime: '2026-08-25T14:00:00.000+02:00',
          },
          {
            status: 'tentative',
            startDateTime: '2026-08-25T15:00:00.000+02:00',
            endDateTime: '2026-08-25T16:00:00.000+02:00',
          },
          {
            status: 'oof',
            startDateTime: '2026-08-25T16:00:00.000+02:00',
            endDateTime: '2026-08-25T17:00:00.000+02:00',
          },
        ],
        items: [
          {
            status: 'busy',
            subject: 'Lunch',
            location: "Harry's Bar",
            isPrivate: false,
            start: { dateTime: '2026-08-25T12:00:00.0000000', timeZone: 'W. Europe Standard Time' },
            end: { dateTime: '2026-08-25T14:00:00.0000000', timeZone: 'W. Europe Standard Time' },
          },
          {
            status: 'busy',
            subject: null,
            location: null,
            isPrivate: true,
            start: { dateTime: '2026-08-25T16:00:00.0000000', timeZone: 'W. Europe Standard Time' },
            end: { dateTime: '2026-08-25T17:00:00.0000000', timeZone: 'W. Europe Standard Time' },
          },
        ],
        workingHours: {
          daysOfWeek: ['monday', 'tuesday'],
          startTime: '08:00:00.0000000',
          endTime: '17:00:00.0000000',
          timeZone: 'W. Europe Standard Time',
        },
      },
    ]);
  });

  it('resolves a relative range and defaults interval to 30 minutes', async () => {
    const { query, post } = createQuery();

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      range: 'today',
      now: NOW,
    });

    expect(result.resolvedWindow?.interpretation).toMatch(/today =/);
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        availabilityViewInterval: 30,
        startTime: { dateTime: '2026-08-25T00:00:00', timeZone: 'W. Europe Standard Time' },
        endTime: { dateTime: '2026-08-25T23:59:59', timeZone: 'W. Europe Standard Time' },
      }),
    );
  });

  it('surfaces error 5006 as a narrow-the-range message', async () => {
    const { query } = createQuery({
      post: vi
        .fn()
        .mockRejectedValue(
          makeGraphError(400, '5006', 'The result set contains too many calendar entries.'),
        ),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      range: 'today',
      now: NOW,
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/1000 calendar entries/);
    expect(result.consentRequired).toBeUndefined();
  });

  it('returns consentRequired when the caller mailbox is denied', async () => {
    const { query } = createQuery({
      post: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      range: 'today',
      now: NOW,
    });

    expect(result.success).toBe(false);
    expect(result.consentRequired).toBe(true);
  });

  it('does not treat a delegated mailbox 403 as missing consent', async () => {
    const { query, api } = createQuery({
      post: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      mailbox: 'banker@example.com',
      range: 'today',
      now: NOW,
    });

    expect(api).toHaveBeenCalledWith(OWNER_PATH);
    expect(result.success).toBe(false);
    expect(result.consentRequired).toBeUndefined();
    expect(result.message).toMatch(/banker@example.com/);
  });

  it('sends UTC wall-clock times when the mailbox timezone cannot be mapped', async () => {
    const { query, post } = createQuery({ timezone: UNMAPPED_TIMEZONE });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      startDateTime: '2026-08-25T09:00:00+02:00',
      endDateTime: '2026-08-25T18:00:00+02:00',
      now: NOW,
    });

    expect(result.availabilityNotes).toEqual([
      'Mailbox timezone "Customized Time Zone" could not be mapped to IANA; relative windows are resolved in UTC.',
    ]);
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        startTime: { dateTime: '2026-08-25T07:00:00', timeZone: 'UTC' },
        endTime: { dateTime: '2026-08-25T16:00:00', timeZone: 'UTC' },
      }),
    );
  });

  it('truncates oversized busy blocks and schedule items', async () => {
    const { query } = createQuery({
      post: vi.fn().mockResolvedValue({
        value: [
          {
            scheduleId: ATTENDEE,
            availabilityView: `${'20'.repeat(101)}`,
            scheduleItems: Array.from({ length: 101 }, (_, index) => ({
              status: 'busy',
              start: { dateTime: `item-${index}` },
              end: { dateTime: `item-${index}` },
            })),
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      startDateTime: '2026-08-25T09:00:00+02:00',
      endDateTime: '2026-08-25T18:00:00+02:00',
      intervalMinutes: 5,
      now: NOW,
    });

    expect(result.people?.[0]?.busyBlocks).toHaveLength(100);
    expect(result.people?.[0]?.items).toHaveLength(100);
    expect(result.availabilityNotes).toEqual([
      `${ATTENDEE}: busy blocks truncated to 100. Narrow the date range.`,
      `${ATTENDEE}: schedule items truncated to 100. Narrow the date range.`,
    ]);
  });

  it('surfaces a per-person 5006 as a narrow-the-range note', async () => {
    const { query } = createQuery({
      post: vi.fn().mockResolvedValue({
        value: [
          {
            scheduleId: ATTENDEE,
            availabilityView: '0',
            error: {
              message: 'The result set contains too many calendar entries.',
              responseCode: '5006',
            },
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      startDateTime: '2026-08-25T09:00:00+02:00',
      endDateTime: '2026-08-25T10:00:00+02:00',
      now: NOW,
    });

    expect(result.success).toBe(true);
    expect(result.availabilityNotes).toEqual([
      `${ATTENDEE}: This window has more than 1000 calendar entries in a slot. Narrow the date range and try again.`,
    ]);
  });

  it('records a per-person Graph error in availabilityNotes', async () => {
    const { query } = createQuery({
      post: vi.fn().mockResolvedValue({
        value: [
          {
            scheduleId: ATTENDEE,
            availabilityView: '0',
            error: { message: 'Mailbox not found', responseCode: 'ErrorMailboxNotFound' },
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      startDateTime: '2026-08-25T09:00:00+02:00',
      endDateTime: '2026-08-25T10:00:00+02:00',
      now: NOW,
    });

    expect(result.success).toBe(true);
    expect(result.availabilityNotes).toEqual([`${ATTENDEE}: Mailbox not found`]);
  });
});
