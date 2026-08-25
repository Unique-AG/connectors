import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { GetCalendarEventQuery } from '../get-calendar-event.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const EVENT_REF = {
  eventId: 'evt-1',
  calendarId: 'cal-own',
  accessPath: 'ownMailbox' as const,
  mailbox: OWN_EMAIL,
};
const PATH = `/users/${OWN_EMAIL}/calendars/cal-own/events/evt-1`;
const PREFER = 'outlook.timezone="W. Europe Standard Time", IdType="ImmutableId"';

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

function createQuery(opts: { get?: ReturnType<typeof vi.fn> } = {}) {
  const get =
    opts.get ??
    vi.fn().mockResolvedValue({
      id: 'evt-1',
      subject: 'Sync',
      start: { dateTime: '2026-08-26T09:00:00', timeZone: 'W. Europe Standard Time' },
      end: { dateTime: '2026-08-26T09:30:00', timeZone: 'W. Europe Standard Time' },
      location: { displayName: 'Room A' },
      attendees: [{}, {}],
      isCancelled: false,
      type: 'occurrence',
      seriesMasterId: 'master-1',
    });
  const request = {
    header: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    get,
  };
  const api = vi.fn().mockReturnValue(request);
  const query = new GetCalendarEventQuery(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as never,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: OWN_EMAIL,
        source: 'oauth',
      }),
    } as never,
    {
      run: vi.fn().mockResolvedValue({
        ianaTimeZone: 'Europe/Zurich',
        outlookTimeZone: 'W. Europe Standard Time',
        notes: [],
      }),
    } as never,
  );
  return { query, api, request, get };
}

describe(GetCalendarEventQuery.name, () => {
  it('loads the event with immutable IDs and mailbox timezone', async () => {
    const { query, api, request } = createQuery();

    const result = await query.run(USER_PROFILE_ID, { eventRef: EVENT_REF });

    expect(api).toHaveBeenCalledWith(PATH);
    expect(request.header).toHaveBeenCalledWith('Prefer', PREFER);
    expect(result.success).toBe(true);
    expect(result.event).toMatchObject({
      eventId: 'evt-1',
      type: 'occurrence',
      seriesMasterId: 'master-1',
      attendeeCount: 2,
      mailbox: OWN_EMAIL,
    });
  });

  it('returns a not-found message on 404', async () => {
    const { query } = createQuery({
      get: vi.fn().mockRejectedValue(makeGraphError(404, 'ErrorItemNotFound')),
    });

    const result = await query.run(USER_PROFILE_ID, { eventRef: EVENT_REF });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not found/i);
  });

  it('returns consentRequired when the caller mailbox is denied', async () => {
    const { query } = createQuery({
      get: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await query.run(USER_PROFILE_ID, { eventRef: EVENT_REF });

    expect(result.success).toBe(false);
    expect(result.consentRequired).toBe(true);
  });
});
