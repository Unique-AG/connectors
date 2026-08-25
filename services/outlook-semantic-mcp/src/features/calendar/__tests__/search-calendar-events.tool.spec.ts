import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import {
  SearchCalendarEventsOutputSchema,
  SearchCalendarEventsTool,
} from '../search-calendar-events.tool';

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
      {
        mailbox: 'me@example.com',
        dateRange: { rangeType: 'relative', range: 'today' },
      },
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
    expect(SearchCalendarEventsOutputSchema.parse(result)).toEqual(output);
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
        dateRange: {
          rangeType: 'absolute',
          startDateTime: '2026-08-25T00:00:00+02:00',
          endDateTime: '2026-08-26T00:00:00+02:00',
        },
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

  it('rejects a relative search without range', async () => {
    const tool = new SearchCalendarEventsTool({ run: vi.fn() } as never);

    await expect(
      tool.searchCalendarEvents(
        { dateRange: { rangeType: 'relative' } } as never,
        {} as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/range/i);
  });

  it('rejects an absolute search without a window', async () => {
    const run = vi.fn();
    const tool = new SearchCalendarEventsTool({ run } as never);

    await expect(
      tool.searchCalendarEvents(
        { dateRange: { rangeType: 'absolute' } } as never,
        {} as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/startDateTime|endDateTime/i);
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects an absolute window without a timezone offset', async () => {
    const run = vi.fn();
    const tool = new SearchCalendarEventsTool({ run } as never);

    await expect(
      tool.searchCalendarEvents(
        {
          dateRange: {
            rangeType: 'absolute',
            startDateTime: '2026-08-25T00:00:00',
            endDateTime: '2026-08-26T00:00:00+02:00',
          },
        },
        {} as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/offset/i);
    expect(run).not.toHaveBeenCalled();
  });
});
