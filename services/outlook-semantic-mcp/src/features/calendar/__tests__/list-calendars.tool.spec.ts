import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { ListCalendarsQuery } from '../list-calendars.query';
import { ListCalendarsOutputSchema, ListCalendarsTool } from '../list-calendars.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

describe(ListCalendarsTool.name, () => {
  it('exposes calendarId only as an opaque calendarRef', async () => {
    const tool = new ListCalendarsTool({
      run: vi.fn().mockResolvedValue({
        success: true,
        message: 'Found 2 calendars.',
        calendars: [
          {
            calendarId: 'cal-own',
            name: 'Calendar',
            ownerEmail: 'me@example.com',
            ownerName: 'Me',
            isOwn: true,
            isDefaultCalendar: true,
            canEdit: true,
            canViewPrivateItems: true,
          },
          {
            // Shared by the banker but stored under the caller, so it is reachable
            // via the same calendarRef shape; only ownerEmail marks it as theirs.
            calendarId: 'cal-shared',
            name: 'Banker',
            ownerEmail: 'banker@example.com',
            ownerName: 'Banker',
            isOwn: false,
            isDefaultCalendar: false,
            canEdit: false,
            canViewPrivateItems: false,
          },
        ],
      }),
    } as unknown as ListCalendarsQuery);

    const result = await tool.listCalendars(
      {},
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(ListCalendarsOutputSchema.parse(result)).toEqual({
      success: true,
      message: 'Found 2 calendars.',
      calendars: [
        {
          calendarRef: { calendarId: 'cal-own' },
          name: 'Calendar',
          ownerEmail: 'me@example.com',
          ownerName: 'Me',
          isOwn: true,
          isDefaultCalendar: true,
          canEdit: true,
          canViewPrivateItems: true,
        },
        {
          calendarRef: { calendarId: 'cal-shared' },
          name: 'Banker',
          ownerEmail: 'banker@example.com',
          ownerName: 'Banker',
          isOwn: false,
          isDefaultCalendar: false,
          canEdit: false,
          canViewPrivateItems: false,
        },
      ],
    });
  });
});
