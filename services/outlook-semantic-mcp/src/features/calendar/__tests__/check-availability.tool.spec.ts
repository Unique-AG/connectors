import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CheckAvailabilityQuery } from '../check-availability.query';
import {
  CheckAvailabilityInputSchema,
  CheckAvailabilityOutputSchema,
  CheckAvailabilityTool,
} from '../check-availability.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');

describe(CheckAvailabilityTool.name, () => {
  it('passes a relative range through to the query', async () => {
    const output = {
      success: true,
      message: 'Checked availability for 1 person.',
      people: [],
      resolvedWindow: {
        startDateTime: '2026-08-25T00:00:00.000+02:00',
        endDateTime: '2026-08-25T23:59:59.999+02:00',
        timeZone: 'Europe/Zurich',
        serverCurrentDateTime: '2026-08-25T15:30:00.000+02:00',
        interpretation: 'today = Tue 2026-08-25 00:00 to Tue 2026-08-25 23:59 (Europe/Zurich)',
      },
    };
    const run = vi.fn().mockResolvedValue(output);
    const tool = new CheckAvailabilityTool({ run } as unknown as CheckAvailabilityQuery);

    const result = await tool.checkAvailability(
      {
        attendees: ['alex@example.com'],
        intervalMinutes: 60,
        dateRange: { rangeType: 'relative', range: 'today' },
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      attendees: ['alex@example.com'],
      intervalMinutes: 60,
      range: 'today',
    });
    expect(CheckAvailabilityOutputSchema.parse(result)).toEqual(output);
  });

  it('passes an absolute window through to the query', async () => {
    const run = vi.fn().mockResolvedValue({
      success: true,
      message: 'Checked availability for 1 person.',
      people: [],
    });
    const tool = new CheckAvailabilityTool({ run } as unknown as CheckAvailabilityQuery);

    await tool.checkAvailability(
      {
        attendees: ['alex@example.com'],
        dateRange: {
          rangeType: 'absolute',
          startDateTime: '2026-08-25T09:00:00+02:00',
          endDateTime: '2026-08-25T18:00:00+02:00',
        },
      },
      {} as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      attendees: ['alex@example.com'],
      intervalMinutes: undefined,
      startDateTime: '2026-08-25T09:00:00+02:00',
      endDateTime: '2026-08-25T18:00:00+02:00',
    });
  });
});

describe('CheckAvailabilityInputSchema', () => {
  it('rejects a window longer than 62 days', () => {
    expect(() =>
      CheckAvailabilityInputSchema.parse({
        attendees: ['alex@example.com'],
        dateRange: { rangeType: 'relative', range: 'next90Days' },
      }),
    ).toThrow(/62 days/);
  });

  it('rejects a whitespace attendee', () => {
    expect(() =>
      CheckAvailabilityInputSchema.parse({
        attendees: ['  '],
        dateRange: { rangeType: 'relative', range: 'today' },
      }),
    ).toThrow(/SMTP/i);
  });

  it('rejects more than 20 attendees', () => {
    expect(() =>
      CheckAvailabilityInputSchema.parse({
        attendees: Array.from({ length: 21 }, (_, index) => `user${index}@example.com`),
        dateRange: { rangeType: 'relative', range: 'today' },
      }),
    ).toThrow(/20/i);
  });

  it('rejects an absolute window without a timezone offset', () => {
    expect(() =>
      CheckAvailabilityInputSchema.parse({
        attendees: ['alex@example.com'],
        dateRange: {
          rangeType: 'absolute',
          startDateTime: '2026-08-25T00:00:00',
          endDateTime: '2026-08-26T00:00:00+02:00',
        },
      }),
    ).toThrow(/offset/i);
  });
});
