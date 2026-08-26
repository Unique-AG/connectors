import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SuggestMeetingTimesQuery } from '../suggest-meeting-times.query';
import {
  SuggestMeetingTimesOutputSchema,
  SuggestMeetingTimesTool,
} from '../suggest-meeting-times.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

describe(SuggestMeetingTimesTool.name, () => {
  it('passes a relative range through to the query', async () => {
    const output = {
      success: true,
      message: 'Found 1 suggested time.',
      suggestions: [],
      emptySuggestionsReason: null,
      resolvedWindow: {
        startDateTime: '2026-08-26T00:00:00.000+02:00',
        endDateTime: '2026-08-26T23:59:59.999+02:00',
        timeZone: 'Europe/Zurich',
        serverCurrentDateTime: '2026-08-25T15:30:00.000+02:00',
        interpretation: 'tomorrow = Wed 2026-08-26 00:00 to Wed 2026-08-26 23:59 (Europe/Zurich)',
      },
    };
    const run = vi.fn().mockResolvedValue(output);
    const tool = new SuggestMeetingTimesTool({ run } as unknown as SuggestMeetingTimesQuery);

    const result = await tool.suggestMeetingTimes(
      {
        attendees: ['alex@example.com'],
        durationMinutes: 45,
        dateRange: { rangeType: 'relative', range: 'tomorrow' },
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      attendees: ['alex@example.com'],
      durationMinutes: 45,
      maxCandidates: undefined,
      activityDomain: undefined,
      isOrganizerOptional: undefined,
      minimumAttendeePercentage: undefined,
      range: 'tomorrow',
    });
    expect(SuggestMeetingTimesOutputSchema.parse(result)).toEqual(output);
  });

  it('passes an absolute window through to the query', async () => {
    const run = vi.fn().mockResolvedValue({
      success: true,
      message: 'Found 1 suggested time.',
      suggestions: [],
    });
    const tool = new SuggestMeetingTimesTool({ run } as unknown as SuggestMeetingTimesQuery);

    await tool.suggestMeetingTimes(
      {
        dateRange: {
          rangeType: 'absolute',
          startDateTime: '2026-08-26T09:00:00+02:00',
          endDateTime: '2026-08-26T18:00:00+02:00',
        },
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(
      USER_PROFILE_ID,
      expect.objectContaining({
        startDateTime: '2026-08-26T09:00:00+02:00',
        endDateTime: '2026-08-26T18:00:00+02:00',
      }),
    );
  });

  it('rejects an absolute window without a timezone offset', async () => {
    const run = vi.fn();
    const tool = new SuggestMeetingTimesTool({ run } as unknown as SuggestMeetingTimesQuery);

    await expect(
      tool.suggestMeetingTimes(
        {
          dateRange: {
            rangeType: 'absolute',
            startDateTime: '2026-08-26T09:00:00',
            endDateTime: '2026-08-26T18:00:00+02:00',
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

  it('rejects a window longer than 62 days', async () => {
    const run = vi.fn();
    const tool = new SuggestMeetingTimesTool({ run } as unknown as SuggestMeetingTimesQuery);

    await expect(
      tool.suggestMeetingTimes(
        { dateRange: { rangeType: 'relative', range: 'next90Days' } },
        {} as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow(/62 days/);
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects a past-only relative range', async () => {
    const run = vi.fn();
    const tool = new SuggestMeetingTimesTool({ run } as unknown as SuggestMeetingTimesQuery);

    await expect(
      tool.suggestMeetingTimes(
        { dateRange: { rangeType: 'relative', range: 'yesterday' } },
        {} as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow(/past/);
    expect(run).not.toHaveBeenCalled();
  });

  it('accepts more than 20 attendees, since findMeetingTimes documents no cap', async () => {
    const run = vi.fn().mockResolvedValue({ success: true, message: 'ok', suggestions: [] });
    const tool = new SuggestMeetingTimesTool({ run } as unknown as SuggestMeetingTimesQuery);
    const attendees = Array.from({ length: 21 }, (_, index) => `user${index}@example.com`);

    await tool.suggestMeetingTimes(
      { attendees, dateRange: { rangeType: 'relative', range: 'today' } },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, expect.objectContaining({ attendees }));
  });
});
