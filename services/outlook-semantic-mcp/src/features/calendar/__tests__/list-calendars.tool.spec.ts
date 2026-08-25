import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { ListCalendarsQueryOutputSchema } from '../list-calendars.query';
import { ListCalendarsTool } from '../list-calendars.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

describe(ListCalendarsTool.name, () => {
  it('returns the query output', async () => {
    const output = {
      success: true,
      message: 'Found 1 calendar.',
      calendars: [
        {
          calendarId: 'cal-1',
          name: 'Calendar',
          ownerEmail: 'me@example.com',
          ownerName: 'Me',
          isOwn: true,
          canEdit: true,
          canViewPrivateItems: true,
          accessPath: 'ownMailbox' as const,
        },
      ],
    };
    const tool = new ListCalendarsTool({
      run: vi.fn().mockResolvedValue(output),
    } as never);

    const result = await tool.listCalendars(
      {},
      {} as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(ListCalendarsQueryOutputSchema.parse(result)).toEqual(output);
  });
});
