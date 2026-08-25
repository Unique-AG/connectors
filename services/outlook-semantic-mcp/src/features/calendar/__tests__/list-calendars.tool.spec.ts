import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { ListCalendarsTool } from '../list-calendars.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

function createTool(queryResult: Awaited<ReturnType<ListCalendarsTool['listCalendars']>>) {
  const listCalendarsQuery = {
    run: vi.fn().mockResolvedValue(queryResult),
  };
  const configService = {
    get: vi.fn().mockReturnValue(new URL('https://outlook.example.com/')),
  };
  const tool = new ListCalendarsTool(listCalendarsQuery as never, configService as never);
  return { tool, listCalendarsQuery };
}

describe(ListCalendarsTool.name, () => {
  it('returns the query output for a successful list', async () => {
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
    const { tool } = createTool(output);
    const elicitUrl = vi.fn();

    const result = await tool.listCalendars(
      {},
      { elicitUrl } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(result).toEqual(output);
    expect(elicitUrl).not.toHaveBeenCalled();
  });

  it('elicits re-authorization when calendar consent is missing', async () => {
    const output = {
      success: false,
      consentRequired: true,
      message: 'Calendar access requires re-authorization.',
    };
    const { tool } = createTool(output);
    const elicitUrl = vi.fn().mockResolvedValue({ action: 'accept' });

    const result = await tool.listCalendars(
      {},
      { elicitUrl } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(result).toEqual(output);
    expect(elicitUrl).toHaveBeenCalledWith(
      expect.objectContaining({
        message: output.message,
        url: 'https://outlook.example.com/auth/authorize',
      }),
    );
  });
});
