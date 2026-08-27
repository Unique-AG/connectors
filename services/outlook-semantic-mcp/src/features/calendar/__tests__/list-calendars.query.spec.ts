import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { ListCalendarsQuery } from '../list-calendars.query';
import { passthroughCalendarMetrics } from './passthrough-calendar-metrics';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const OWNER_EMAIL = 'banker@example.com';
const OWN_PATH = `/me/calendars`;
const CALENDAR_SELECT =
  'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar,isTallyingResponses';

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

function createQuery(opts: { email?: string; get?: ReturnType<typeof vi.fn> }) {
  const get = opts.get ?? vi.fn().mockResolvedValue({ value: [] });
  const request = {
    select: vi.fn().mockReturnThis(),
    top: vi.fn().mockReturnThis(),
    get,
  };
  const api = vi.fn().mockReturnValue(request);

  const query = new ListCalendarsQuery(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as unknown as GraphClientFactory,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: opts.email ?? OWN_EMAIL,
        source: 'oauth',
      }),
    } as unknown as GetUserProfileQuery,
    passthroughCalendarMetrics() as unknown as CalendarMetricsService,
  );

  return { query, api, request };
}

describe(ListCalendarsQuery.name, () => {
  it('GETs /users/{email}/calendars and classifies own and shared calendars', async () => {
    const { query, api, request } = createQuery({
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

    expect(api).toHaveBeenCalledWith(OWN_PATH);
    expect(api).toHaveBeenCalledTimes(1);
    expect(request.select).toHaveBeenCalledWith(CALENDAR_SELECT);
    expect(result.success).toBe(true);
    expect(result.calendars).toEqual([
      expect.objectContaining({
        calendarId: 'cal-own',
        isOwn: true,
        isDefaultCalendar: true,
      }),
      expect.objectContaining({
        calendarId: 'cal-primary',
        isOwn: false,
        isDefaultCalendar: false,
        ownerEmail: OWNER_EMAIL,
      }),
      expect.objectContaining({
        calendarId: 'cal-custom',
        isOwn: false,
        isDefaultCalendar: false,
        ownerEmail: OWNER_EMAIL,
      }),
    ]);
  });

  it('lists primary calendars ahead of holiday and extra calendars', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          {
            id: 'cal-holidays',
            name: 'United States holidays',
            isDefaultCalendar: false,
            owner: { address: OWN_EMAIL, name: 'Me' },
          },
          {
            id: 'cal-own',
            name: 'Calendar',
            isDefaultCalendar: true,
            owner: { address: OWN_EMAIL, name: 'Me' },
          },
          {
            id: 'cal-birthdays',
            name: 'Birthdays',
            isDefaultCalendar: false,
            owner: { address: OWN_EMAIL, name: 'Me' },
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(result.calendars?.map((calendar) => calendar.calendarId)).toEqual([
      'cal-own',
      'cal-holidays',
      'cal-birthdays',
    ]);
    expect(result.calendars?.[0]).toEqual(
      expect.objectContaining({ calendarId: 'cal-own', isDefaultCalendar: true }),
    );
  });

  it('returns consentRequired when Graph denies calendar scopes on the caller mailbox', async () => {
    const { query } = createQuery({
      get: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(result).toEqual({
      success: false,
      consentRequired: true,
      errorType: 'consent',
      message: expect.stringContaining('re-authorization'),
    });
  });

  it('pages through @odata.nextLink', async () => {
    const get = vi
      .fn()
      .mockResolvedValueOnce({
        value: [{ id: 'cal-1', owner: { address: OWN_EMAIL } }],
        '@odata.nextLink': `https://graph.microsoft.com/v1.0/me/calendars?$skiptoken=abc`,
      })
      .mockResolvedValueOnce({
        value: [{ id: 'cal-2', owner: { address: OWN_EMAIL } }],
      });
    const { query, api } = createQuery({ get });

    const result = await query.run(USER_PROFILE_ID);

    expect(api).toHaveBeenNthCalledWith(1, OWN_PATH);
    expect(api).toHaveBeenNthCalledWith(
      2,
      `https://graph.microsoft.com/v1.0/me/calendars?$skiptoken=abc`,
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

  it('keeps calendars whose Graph owner is null', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({
        value: [
          {
            id: 'cal-own',
            name: 'Calendar',
            isDefaultCalendar: true,
            owner: { address: OWN_EMAIL, name: 'Me' },
          },
          {
            id: 'cal-shared',
            name: 'Banker',
            owner: { address: OWNER_EMAIL, name: 'Banker' },
          },
          {
            id: 'cal-no-owner',
            name: 'Holidays',
            isDefaultCalendar: false,
            owner: null,
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID);

    expect(result.success).toBe(true);
    expect(result.calendars).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          calendarId: 'cal-no-owner',
          isOwn: false,
          ownerEmail: null,
          ownerName: null,
        }),
      ]),
    );
  });

  it('fails when Graph returns a calendar without an id', async () => {
    const { query } = createQuery({
      get: vi.fn().mockResolvedValue({ value: [{ name: 'Broken' }] }),
    });

    await expect(query.run(USER_PROFILE_ID)).rejects.toThrow();
  });
});
