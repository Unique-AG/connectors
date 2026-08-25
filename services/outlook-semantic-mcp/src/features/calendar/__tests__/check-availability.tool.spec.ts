import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CheckAvailabilityOutputSchema, CheckAvailabilityTool } from '../check-availability.tool';

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
    const tool = new CheckAvailabilityTool({ run } as never);

    const result = await tool.checkAvailability(
      {
        attendees: ['alex@example.com'],
        mailbox: 'me@example.com',
        intervalMinutes: 60,
        dateRange: { rangeType: 'relative', range: 'today' },
      },
      {} as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      attendees: ['alex@example.com'],
      mailbox: 'me@example.com',
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
    const tool = new CheckAvailabilityTool({ run } as never);

    await tool.checkAvailability(
      {
        attendees: ['alex@example.com'],
        dateRange: {
          rangeType: 'absolute',
          startDateTime: '2026-08-25T09:00:00+02:00',
          endDateTime: '2026-08-25T18:00:00+02:00',
        },
      },
      {} as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      attendees: ['alex@example.com'],
      mailbox: undefined,
      intervalMinutes: undefined,
      startDateTime: '2026-08-25T09:00:00+02:00',
      endDateTime: '2026-08-25T18:00:00+02:00',
    });
  });

  it('rejects a mailbox that is not an SMTP address', async () => {
    const run = vi.fn();
    const tool = new CheckAvailabilityTool({ run } as never);

    await expect(
      tool.checkAvailability(
        {
          attendees: ['alex@example.com'],
          mailbox: 'not/an/email',
          dateRange: { rangeType: 'relative', range: 'today' },
        },
        {} as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/SMTP/i);
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects a window longer than 62 days', async () => {
    const run = vi.fn();
    const tool = new CheckAvailabilityTool({ run } as never);

    await expect(
      tool.checkAvailability(
        {
          attendees: ['alex@example.com'],
          dateRange: { rangeType: 'relative', range: 'next90Days' },
        },
        {} as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/62 days/);
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects a whitespace attendee', async () => {
    const run = vi.fn();
    const tool = new CheckAvailabilityTool({ run } as never);

    await expect(
      tool.checkAvailability(
        {
          attendees: ['  '],
          dateRange: { rangeType: 'relative', range: 'today' },
        },
        {} as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/SMTP/i);
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects more than 20 attendees before calling the query', async () => {
    const run = vi.fn();
    const tool = new CheckAvailabilityTool({ run } as never);

    await expect(
      tool.checkAvailability(
        {
          attendees: Array.from({ length: 21 }, (_, index) => `user${index}@example.com`),
          dateRange: { rangeType: 'relative', range: 'today' },
        },
        {} as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/20/i);
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects an absolute window without a timezone offset', async () => {
    const run = vi.fn();
    const tool = new CheckAvailabilityTool({ run } as never);

    await expect(
      tool.checkAvailability(
        {
          attendees: ['alex@example.com'],
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
