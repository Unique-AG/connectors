import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { ListCalendarsOutputSchema, ListCalendarsTool } from '../list-calendars.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

describe(ListCalendarsTool.name, () => {
  it('bundles calendarId and its mailbox into an opaque calendarRef', async () => {
    const tool = new ListCalendarsTool({
      run: vi.fn().mockResolvedValue({
        success: true,
        message: 'Found 2 calendars.',
        calendars: [
          {
            calendarId: 'cal-own',
            name: 'Calendar',
            mailbox: 'me@example.com',
            ownerEmail: 'me@example.com',
            ownerName: 'Me',
            isOwn: true,
            canEdit: true,
            canViewPrivateItems: true,
          },
          {
            // Shared by the banker but stored in the caller mailbox, so calendarRef.mailbox is
            // the caller — not the owner.
            calendarId: 'cal-shared',
            name: 'Banker',
            mailbox: 'me@example.com',
            ownerEmail: 'banker@example.com',
            ownerName: 'Banker',
            isOwn: false,
            canEdit: false,
            canViewPrivateItems: false,
          },
        ],
      }),
    } as never);

    const result = await tool.listCalendars(
      {},
      {} as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(ListCalendarsOutputSchema.parse(result)).toEqual({
      success: true,
      message: 'Found 2 calendars.',
      calendars: [
        {
          calendarRef: { calendarId: 'cal-own', mailbox: 'me@example.com' },
          name: 'Calendar',
          ownerEmail: 'me@example.com',
          ownerName: 'Me',
          isOwn: true,
          canEdit: true,
          canViewPrivateItems: true,
        },
        {
          calendarRef: { calendarId: 'cal-shared', mailbox: 'me@example.com' },
          name: 'Banker',
          ownerEmail: 'banker@example.com',
          ownerName: 'Banker',
          isOwn: false,
          canEdit: false,
          canViewPrivateItems: false,
        },
      ],
    });
  });
});
