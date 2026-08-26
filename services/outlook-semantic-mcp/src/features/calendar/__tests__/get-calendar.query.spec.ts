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

    expect(api).toHaveBeenCalledWith(`/users/${OWN_EMAIL}/calendar`);
    expect(result.calendar).toEqual({
      calendarId: 'cal-own',
      mailbox: OWN_EMAIL,
      name: 'Calendar',
      isDefaultCalendar: true,
      isOwn: true,
      ownerEmail: OWN_EMAIL,
      ownerName: 'Me',
      canEdit: true,
    });
  });

  it('reads a shared calendar from the mailbox on the ref, not from its owner', async () => {
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
      calendarRef: { calendarId: 'cal-shared', mailbox: OWN_EMAIL },
    });

    expect(api).toHaveBeenCalledWith(`/users/${OWN_EMAIL}/calendars/cal-shared`);
    expect(result.calendar).toMatchObject({
      mailbox: OWN_EMAIL,
      isOwn: false,
      ownerEmail: 'banker@example.com',
    });
  });

  it('returns a not-found message on 404', async () => {
    const { query } = createQuery({
      get: vi.fn().mockRejectedValue(new GraphError(404, 'ErrorItemNotFound')),
    });

    const result = await query.run(USER_PROFILE_ID, {
      calendarRef: { calendarId: 'gone', mailbox: OWN_EMAIL },
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
