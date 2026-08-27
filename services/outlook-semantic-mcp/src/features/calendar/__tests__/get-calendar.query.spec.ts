import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { GetCalendarQuery } from '../get-calendar.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';

function createQuery(opts: { get?: ReturnType<typeof vi.fn> } = {}) {
  const get = opts.get ?? vi.fn().mockResolvedValue({ id: 'cal-own', name: 'Calendar' });
  const api = vi.fn().mockReturnValue({ select: vi.fn().mockReturnThis(), get });
  const query = new GetCalendarQuery(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as unknown as GraphClientFactory,
    {
      run: vi
        .fn()
        .mockResolvedValue({ id: USER_PROFILE_ID.toString(), email: OWN_EMAIL, source: 'oauth' }),
    } as unknown as GetUserProfileQuery,
  );
  return { query, api, get };
}

describe(GetCalendarQuery.name, () => {
  it('reads the signed-in user default calendar when no ref is given', async () => {
    const { query, api } = createQuery({
      get: vi.fn().mockResolvedValue({
        id: 'cal-own',
        name: 'Calendar',
        isDefaultCalendar: true,
        canEdit: true,
        owner: { address: OWN_EMAIL, name: 'Me' },
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {});

    expect(api).toHaveBeenCalledWith(`/me/calendar`);
    expect(result.calendar).toEqual({
      calendarId: 'cal-own',
      name: 'Calendar',
      isDefaultCalendar: true,
      isOwn: true,
      ownerEmail: OWN_EMAIL,
      ownerName: 'Me',
      canEdit: true,
    });
  });

  it('reads a shared calendar under /me, not under its owner', async () => {
    const { query, api } = createQuery({
      get: vi.fn().mockResolvedValue({
        id: 'cal-shared',
        name: 'Banker',
        isDefaultCalendar: false,
        canEdit: true,
        owner: { address: 'banker@example.com', name: 'Banker' },
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      calendarRef: { calendarId: 'cal-shared' },
    });

    expect(api).toHaveBeenCalledWith(`/me/calendars/cal-shared`);
    expect(result.calendar).toMatchObject({
      isOwn: false,
      ownerEmail: 'banker@example.com',
    });
  });

  it('treats a Graph null owner as unknown rather than failing', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        id: 'cal-no-owner',
        name: 'Holidays',
        isDefaultCalendar: false,
        canEdit: false,
        owner: null,
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      calendarRef: { calendarId: 'cal-no-owner' },
    });

    expect(result.success).toBe(true);
    expect(result.calendar).toMatchObject({
      calendarId: 'cal-no-owner',
      isOwn: false,
      ownerEmail: null,
      ownerName: null,
    });
  });

  it('returns a not-found message on 404', async () => {
    const { query } = createQuery({
      get: vi.fn().mockRejectedValue(new GraphError(404, 'ErrorItemNotFound')),
    });

    const result = await query.run(USER_PROFILE_ID, {
      calendarRef: { calendarId: 'gone' },
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not found/i);
  });

  it('returns consentRequired when the caller mailbox is denied', async () => {
    const { query } = createQuery({
      get: vi.fn().mockRejectedValue(new GraphError(403, 'ErrorAccessDenied')),
    });

    const result = await query.run(USER_PROFILE_ID, {});

    expect(result.success).toBe(false);
    expect(result.consentRequired).toBe(true);
  });
});
