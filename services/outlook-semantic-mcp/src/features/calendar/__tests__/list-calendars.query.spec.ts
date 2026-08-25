import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import {
  AllDelegatesFailedError,
  NoDelegatesFoundError,
} from '~/msgraph/ms-graph-client-resolver.service';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { ListCalendarsQuery } from '../list-calendars.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const SHARED_EMAIL = 'shared@example.com';
const OWNER_EMAIL = 'banker@example.com';
const CALENDAR_SELECT =
  'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar,isTallyingResponses';

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

function createQuery(opts: {
  source?: 'oauth' | 'shared-mailbox';
  email?: string;
  get?: ReturnType<typeof vi.fn>;
  responsesByPath?: Record<string, unknown | Error>;
  resolverRun?: ReturnType<typeof vi.fn>;
  fullAccessOwners?: string[];
}) {
  const get = opts.get ?? vi.fn().mockResolvedValue({ value: [] });
  const request = {
    select: vi.fn().mockReturnThis(),
    top: vi.fn().mockReturnThis(),
    get,
  };
  const api =
    opts.responsesByPath === undefined
      ? vi.fn().mockReturnValue(request)
      : vi.fn().mockImplementation((path: string) => {
          const response = opts.responsesByPath?.[path];
          const pathGet =
            response instanceof Error
              ? vi.fn().mockRejectedValue(response)
              : vi.fn().mockResolvedValue(response ?? { value: [] });
          return {
            select: vi.fn().mockReturnThis(),
            top: vi.fn().mockReturnThis(),
            get: pathGet,
          };
        });
  const resolverRun =
    opts.resolverRun ??
    vi
      .fn()
      .mockImplementation(async ({ fn }) =>
        fn({ client: { api }, clientUserProfileId: 'client-1' }),
      );
  const getFullDelegatedAccess = vi
    .fn()
    .mockResolvedValue((opts.fullAccessOwners ?? []).map((ownerUserEmail) => ({ ownerUserEmail })));

  const query = new ListCalendarsQuery(
    { run: resolverRun } as never,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: opts.email ?? OWN_EMAIL,
        source: opts.source ?? 'oauth',
      }),
    } as never,
    { run: getFullDelegatedAccess } as never,
  );

  return { query, api, request, resolverRun, getFullDelegatedAccess };
}

describe(ListCalendarsQuery.name, () => {
  it('GETs /me/calendars and classifies own, delegated-primary, and shared-custom calendars', async () => {
    const { query, api, request, getFullDelegatedAccess } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          {
            id: 'cal-own',
            name: 'Calendar',
            isDefaultCalendar: true,
            isTallyingResponses: true,
            canEdit: true,
            canViewPrivateItems: true,
            owner: { address: OWN_EMAIL, name: 'Me' },
          },
          {
            id: 'cal-primary',
            name: 'Banker',
            isDefaultCalendar: false,
            isTallyingResponses: true,
            canEdit: true,
            canViewPrivateItems: false,
            owner: { address: OWNER_EMAIL, name: 'Banker' },
          },
          {
            id: 'cal-custom',
            name: 'Projects',
            isDefaultCalendar: false,
            isTallyingResponses: false,
            canEdit: false,
            canViewPrivateItems: false,
            owner: { address: OWNER_EMAIL, name: 'Banker' },
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(api).toHaveBeenCalledWith('/me/calendars');
    expect(request.select).toHaveBeenCalledWith(CALENDAR_SELECT);
    expect(getFullDelegatedAccess).toHaveBeenCalledWith(USER_PROFILE_ID.toString());
    expect(result.success).toBe(true);
    expect(result.calendars).toEqual([
      expect.objectContaining({ calendarId: 'cal-own', isOwn: true, accessPath: 'ownMailbox' }),
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

  it('unions Full Access owner calendars from /users/{owner}/calendars', async () => {
    const { query, api } = createQuery({
      fullAccessOwners: [OWNER_EMAIL],
      responsesByPath: {
        '/me/calendars': {
          value: [
            {
              id: 'cal-own',
              name: 'Calendar',
              owner: { address: OWN_EMAIL, name: 'Me' },
            },
            {
              id: 'cal-local-copy',
              name: 'Banker',
              owner: { address: OWNER_EMAIL, name: 'Banker' },
            },
          ],
        },
        [`/users/${OWNER_EMAIL}/calendars`]: {
          value: [
            {
              id: 'cal-owner-primary',
              name: 'Calendar',
              isDefaultCalendar: true,
              canEdit: true,
              owner: { address: OWNER_EMAIL, name: 'Banker' },
            },
          ],
        },
      },
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(api).toHaveBeenCalledWith('/me/calendars');
    expect(api).toHaveBeenCalledWith(`/users/${OWNER_EMAIL}/calendars`);
    expect(result.success).toBe(true);
    expect(result.calendars).toEqual([
      expect.objectContaining({ calendarId: 'cal-own', isOwn: true, accessPath: 'ownMailbox' }),
      expect.objectContaining({
        calendarId: 'cal-owner-primary',
        isOwn: false,
        accessPath: 'ownerMailbox',
        ownerEmail: OWNER_EMAIL,
      }),
    ]);
    expect(result.calendars?.map((calendar) => calendar.calendarId)).not.toContain(
      'cal-local-copy',
    );
  });

  it('keeps /me calendars when a Full Access mailbox returns 403', async () => {
    const { query } = createQuery({
      fullAccessOwners: [OWNER_EMAIL],
      responsesByPath: {
        '/me/calendars': {
          value: [
            {
              id: 'cal-local-copy',
              name: 'Banker',
              owner: { address: OWNER_EMAIL, name: 'Banker' },
            },
          ],
        },
        [`/users/${OWNER_EMAIL}/calendars`]: makeGraphError(403, 'ErrorAccessDenied'),
      },
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(result.success).toBe(true);
    expect(result.consentRequired).toBeUndefined();
    expect(result.calendars).toEqual([
      expect.objectContaining({ calendarId: 'cal-local-copy', ownerEmail: OWNER_EMAIL }),
    ]);
  });

  it('GETs /users/{email}/calendars for a shared-mailbox profile', async () => {
    const { query, api, resolverRun, getFullDelegatedAccess } = createQuery({
      source: 'shared-mailbox',
      email: SHARED_EMAIL,
      get: vi.fn().mockResolvedValue({
        value: [
          {
            id: 'cal-shared',
            name: 'Support',
            isDefaultCalendar: true,
            owner: { address: SHARED_EMAIL, name: 'Support' },
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(resolverRun).toHaveBeenCalledWith(
      expect.objectContaining({
        sharedMailboxConfig: { throwIfNoDelegates: true },
      }),
    );
    expect(api).toHaveBeenCalledWith(`/users/${SHARED_EMAIL}/calendars`);
    expect(getFullDelegatedAccess).not.toHaveBeenCalled();
    expect(result.success).toBe(true);
    expect(result.calendars).toEqual([
      expect.objectContaining({ calendarId: 'cal-shared', isOwn: true, accessPath: 'ownMailbox' }),
    ]);
  });

  it('returns consentRequired when Graph denies calendar scopes on /me/calendars', async () => {
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

  it('does not leak internal user-profile IDs when no delegates exist', async () => {
    const { query } = createQuery({
      source: 'shared-mailbox',
      email: SHARED_EMAIL,
      resolverRun: vi.fn().mockRejectedValue(new NoDelegatesFoundError(USER_PROFILE_ID.toString())),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(result.success).toBe(false);
    expect(result.message).not.toContain(USER_PROFILE_ID.toString());
    expect(result.message).toContain('shared mailbox');
  });

  it('does not leak internal user-profile IDs when all delegates fail', async () => {
    const { query } = createQuery({
      source: 'shared-mailbox',
      email: SHARED_EMAIL,
      resolverRun: vi
        .fn()
        .mockRejectedValue(new AllDelegatesFailedError(USER_PROFILE_ID.toString())),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(result.success).toBe(false);
    expect(result.message).not.toContain(USER_PROFILE_ID.toString());
  });

  it('pages through @odata.nextLink', async () => {
    const get = vi
      .fn()
      .mockResolvedValueOnce({
        value: [{ id: 'cal-1', owner: { address: OWN_EMAIL } }],
        '@odata.nextLink': 'https://graph.microsoft.com/v1.0/me/calendars?$skiptoken=abc',
      })
      .mockResolvedValueOnce({
        value: [{ id: 'cal-2', owner: { address: OWN_EMAIL } }],
      });
    const { query, api } = createQuery({ get });

    const result = await query.run(USER_PROFILE_ID);

    expect(api).toHaveBeenNthCalledWith(1, '/me/calendars');
    expect(api).toHaveBeenNthCalledWith(
      2,
      'https://graph.microsoft.com/v1.0/me/calendars?$skiptoken=abc',
    );
    expect(result.success).toBe(true);
    expect(result.calendars?.map((calendar) => calendar.calendarId)).toEqual(['cal-1', 'cal-2']);
  });

  it('returns an empty-list message when Graph returns no calendars', async () => {
    const { query } = createQuery({ get: vi.fn().mockResolvedValue({ value: [] }) });

    const result = await query.run(USER_PROFILE_ID);

    expect(result).toEqual({
      success: true,
      message: 'No calendars were returned.',
      calendars: [],
    });
  });

  it('fails when Graph returns a calendar without an id', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [{ name: 'Broken' }] }),
    });

    await expect(query.run(USER_PROFILE_ID)).rejects.toThrow();
  });
});
