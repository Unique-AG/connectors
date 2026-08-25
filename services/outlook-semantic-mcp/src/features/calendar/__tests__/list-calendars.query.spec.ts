import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { ListCalendarsQuery } from '../list-calendars.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const SHARED_EMAIL = 'shared@example.com';
const OWNER_EMAIL = 'banker@example.com';

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

function makeRequest(get: ReturnType<typeof vi.fn>) {
  return {
    select: vi.fn().mockReturnThis(),
    get,
  };
}

function createQuery(opts: {
  source?: 'oauth' | 'shared-mailbox';
  email?: string;
  get?: ReturnType<typeof vi.fn>;
  resolverRun?: ReturnType<typeof vi.fn>;
}) {
  const get = opts.get ?? vi.fn().mockResolvedValue({ value: [] });
  const request = makeRequest(get);
  const graphClientFactory = {
    createClientForUser: vi.fn().mockReturnValue({
      api: vi.fn().mockReturnValue(request),
    }),
  };
  const msGraphClientResolver = {
    run: opts.resolverRun ?? vi.fn(),
  };
  const getUserProfileQuery = {
    run: vi.fn().mockResolvedValue({
      id: USER_PROFILE_ID.toString(),
      email: opts.email ?? OWN_EMAIL,
      source: opts.source ?? 'oauth',
    }),
  };

  const query = new ListCalendarsQuery(
    graphClientFactory as never,
    msGraphClientResolver as never,
    getUserProfileQuery as never,
  );

  return { query, get, request, graphClientFactory, msGraphClientResolver };
}

describe(ListCalendarsQuery.name, () => {
  it('lists own and shared calendars with accessPath classified from Graph', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          {
            id: 'cal-own',
            name: 'Calendar',
            isDefaultCalendar: true,
            canEdit: true,
            canViewPrivateItems: true,
            owner: { address: OWN_EMAIL, name: 'Me' },
          },
          {
            id: 'cal-primary',
            name: 'Banker',
            isDefaultCalendar: true,
            canEdit: true,
            canViewPrivateItems: false,
            owner: { address: OWNER_EMAIL, name: 'Banker' },
          },
          {
            id: 'cal-custom',
            name: 'Projects',
            isDefaultCalendar: false,
            canEdit: false,
            canViewPrivateItems: false,
            owner: { address: OWNER_EMAIL, name: 'Banker' },
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(result.success).toBe(true);
    expect(result.calendars).toEqual([
      expect.objectContaining({
        calendarId: 'cal-own',
        isOwn: true,
        accessPath: 'ownMailbox',
      }),
      expect.objectContaining({
        calendarId: 'cal-primary',
        isOwn: false,
        accessPath: 'ownerMailbox',
        ownerEmail: OWNER_EMAIL,
      }),
      expect.objectContaining({
        calendarId: 'cal-custom',
        isOwn: false,
        accessPath: 'ownMailbox',
        ownerEmail: OWNER_EMAIL,
      }),
    ]);
  });

  it('returns consentRequired when Graph denies calendar scopes', async () => {
    const { query } = createQuery({
      get: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(result).toEqual({
      success: false,
      consentRequired: true,
      message: expect.stringContaining('re-authorization'),
    });
  });

  it('lists calendars on a shared-mailbox profile through the delegate resolver', async () => {
    const get = vi.fn().mockResolvedValue({
      value: [
        {
          id: 'cal-shared',
          name: 'Support',
          isDefaultCalendar: true,
          canEdit: true,
          canViewPrivateItems: true,
          owner: { address: SHARED_EMAIL, name: 'Support' },
        },
      ],
    });
    const request = makeRequest(get);
    const resolverRun = vi
      .fn()
      .mockImplementation(async ({ fn }) =>
        fn({ client: { api: vi.fn().mockReturnValue(request) }, clientUserProfileId: 'delegate' }),
      );
    const { query, graphClientFactory } = createQuery({
      source: 'shared-mailbox',
      email: SHARED_EMAIL,
      resolverRun,
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(graphClientFactory.createClientForUser).not.toHaveBeenCalled();
    expect(resolverRun).toHaveBeenCalledOnce();
    expect(request.select).toHaveBeenCalledWith(
      'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar',
    );
    expect(result.success).toBe(true);
    expect(result.calendars).toEqual([
      expect.objectContaining({
        calendarId: 'cal-shared',
        isOwn: true,
        accessPath: 'ownMailbox',
      }),
    ]);
  });
});
