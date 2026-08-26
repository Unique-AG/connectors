import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SearchCalendarEventsQuery } from '../search-calendar-events.query';
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
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    const result = await tool.searchCalendarEvents(
      {
        mailbox: 'me@example.com',
        dateRange: { rangeType: 'relative', range: 'today' },
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      mailbox: 'me@example.com',
      range: 'today',
    });
    expect(SearchCalendarEventsOutputSchema.parse(result)).toEqual(output);
  });

  it('passes the subject and attendee filters through unchanged', async () => {
    const run = vi.fn().mockResolvedValue({ success: true, message: 'ok', events: [] });
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    await tool.searchCalendarEvents(
      {
        dateRange: { rangeType: 'relative', range: 'thisWeek' },
        subject: { startsWith: 'Weekly' },
        attendees: ['alex@example.com', 'pat@example.com'],
        categories: ['Client', 'Urgent'],
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      subject: { startsWith: 'Weekly' },
      attendees: ['alex@example.com', 'pat@example.com'],
      categories: ['Client', 'Urgent'],
      range: 'thisWeek',
    });
  });

  it('rejects a subject filter that sets both startsWith and contains', async () => {
    const run = vi.fn();
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    await expect(
      tool.searchCalendarEvents(
        {
          dateRange: { rangeType: 'relative', range: 'today' },
          subject: { startsWith: 'Weekly', contains: 'Sales' },
        } as unknown as Parameters<SearchCalendarEventsTool['searchCalendarEvents']>[0],
        {} as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow();
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects an attendee that is not an SMTP address', async () => {
    const run = vi.fn();
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    await expect(
      tool.searchCalendarEvents(
        {
          dateRange: { rangeType: 'relative', range: 'today' },
          attendees: ['Alex'],
        },
        {} as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow(/SMTP/i);
    expect(run).not.toHaveBeenCalled();
  });

  it('passes an absolute window through to the query', async () => {
    const run = vi.fn().mockResolvedValue({
      success: true,
      message: 'No events matched the search.',
      events: [],
    });
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    await tool.searchCalendarEvents(
      {
        dateRange: {
          rangeType: 'absolute',
          startDateTime: '2026-08-25T00:00:00+02:00',
          endDateTime: '2026-08-26T00:00:00+02:00',
        },
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      startDateTime: '2026-08-25T00:00:00+02:00',
      endDateTime: '2026-08-26T00:00:00+02:00',
    });
  });

  it('rejects a relative search without range', async () => {
    const tool = new SearchCalendarEventsTool({
      run: vi.fn(),
    } as unknown as SearchCalendarEventsQuery);

    await expect(
      tool.searchCalendarEvents(
        { dateRange: { rangeType: 'relative' } } as unknown as Parameters<
          SearchCalendarEventsTool['searchCalendarEvents']
        >[0],
        {} as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow(/range/i);
  });

  it('rejects an absolute search without a window', async () => {
    const run = vi.fn();
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    await expect(
      tool.searchCalendarEvents(
        { dateRange: { rangeType: 'absolute' } } as unknown as Parameters<
          SearchCalendarEventsTool['searchCalendarEvents']
        >[0],
        {} as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow(/startDateTime|endDateTime/i);
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects an absolute window without a timezone offset', async () => {
    const run = vi.fn();
    const tool = new SearchCalendarEventsTool({ run } as unknown as SearchCalendarEventsQuery);

    await expect(
      tool.searchCalendarEvents(
        {
          dateRange: {
            rangeType: 'absolute',
            startDateTime: '2026-08-25T00:00:00',
            endDateTime: '2026-08-26T00:00:00+02:00',
          },
        },
        {} as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow(/offset/i);
    expect(run).not.toHaveBeenCalled();
  });
});
