import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SearchCalendarEventsQueryOutputSchema } from '../search-calendar-events.query';
import { SearchCalendarEventsTool } from '../search-calendar-events.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

describe(SearchCalendarEventsTool.name, () => {
  it('passes a relative range through to the query', async () => {
    const output = {
      success: true,
      message: 'Found 1 event.',
      events: [],
      resolvedWindow: {
        startDateTime: '2026-08-25T00:00:00.000+02:00',
        endDateTime: '2026-08-25T23:59:59.999+02:00',
        timeZone: 'Europe/Zurich',
        serverCurrentDateTime: '2026-08-25T15:30:00.000+02:00',
        interpretation: 'today = Tue 2026-08-25 00:00 to Tue 2026-08-25 23:59 (Europe/Zurich)',
      },
    };
    const run = vi.fn().mockResolvedValue(output);
    const tool = new SearchCalendarEventsTool({ run } as never);

    const result = await tool.searchCalendarEvents(
      { rangeType: 'relative', range: 'today', mailbox: 'me@example.com' },
      {} as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      mailbox: 'me@example.com',
      attendee: undefined,
      subject: undefined,
      category: undefined,
      range: 'today',
    });
    expect(SearchCalendarEventsQueryOutputSchema.parse(result)).toEqual(output);
  });

  it('passes an absolute window through to the query', async () => {
    const run = vi.fn().mockResolvedValue({
      success: true,
      message: 'No events matched the search.',
      events: [],
    });
    const tool = new SearchCalendarEventsTool({ run } as never);

    await tool.searchCalendarEvents(
      {
        rangeType: 'absolute',
        startDateTime: '2026-08-25T00:00:00+02:00',
        endDateTime: '2026-08-26T00:00:00+02:00',
      },
      {} as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      mailbox: undefined,
      attendee: undefined,
      subject: undefined,
      category: undefined,
      startDateTime: '2026-08-25T00:00:00+02:00',
      endDateTime: '2026-08-26T00:00:00+02:00',
    });
  });
});
