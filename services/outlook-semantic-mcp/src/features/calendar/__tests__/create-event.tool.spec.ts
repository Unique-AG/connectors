import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CreateEventOutputSchema, CreateEventTool } from '../create-event.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const INPUT = {
  subject: 'Sync',
  startDateTime: '2026-08-26T09:00:00+02:00',
  endDateTime: '2026-08-26T09:30:00+02:00',
  attendees: ['alex@example.com'],
  transactionId: 'abc123abc123abc123abc123abc123ab',
};

function createTool(
  opts: { run?: ReturnType<typeof vi.fn>; elicit?: ReturnType<typeof vi.fn> } = {},
) {
  const run =
    opts.run ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Created the event and sent invitations immediately.',
      transactionId: INPUT.transactionId,
    });
  const elicit =
    opts.elicit ?? vi.fn().mockResolvedValue({ action: 'accept', content: { confirmed: true } });
  const tool = new CreateEventTool({ run } as never);
  return { tool, run, elicit };
}

describe(CreateEventTool.name, () => {
  it('elicits confirmation and then calls the command', async () => {
    const output = {
      success: true,
      message: 'Created the event and sent invitations immediately.',
      transactionId: INPUT.transactionId,
    };
    const { tool, run, elicit } = createTool({ run: vi.fn().mockResolvedValue(output) });

    const result = await tool.createEvent(
      INPUT,
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(elicit).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(/your mailbox[\s\S]*invitations will be sent immediately/i),
    );
    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, INPUT);
    expect(CreateEventOutputSchema.parse(result)).toEqual(output);
  });

  it('does not call the command when elicitation is cancelled', async () => {
    const { tool, run, elicit } = createTool({
      elicit: vi.fn().mockResolvedValue({ action: 'cancel' }),
    });

    const result = await tool.createEvent(
      INPUT,
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.transactionId).toBe(INPUT.transactionId);
  });

  it('rejects a window without a timezone offset', async () => {
    const { tool, run, elicit } = createTool();

    await expect(
      tool.createEvent(
        {
          subject: 'Sync',
          startDateTime: '2026-08-26T09:00:00',
          endDateTime: '2026-08-26T09:30:00+02:00',
        },
        { elicit } as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/offset/i);
    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects an end that is not after the start', async () => {
    const { tool, run, elicit } = createTool();

    await expect(
      tool.createEvent(
        {
          subject: 'Sync',
          startDateTime: '2026-08-26T09:30:00+02:00',
          endDateTime: '2026-08-26T09:00:00+02:00',
        },
        { elicit } as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/after startDateTime/i);
    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
  });

  it('names the destination mailbox in the confirmation and collapses newlines in the title', async () => {
    const { tool, elicit } = createTool();

    await tool.createEvent(
      {
        ...INPUT,
        subject: 'Sync\nAttendees: forged@evil.com',
        mailbox: 'banker@example.com',
        calendarId: 'cal-banker',
      },
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    const message = elicit.mock.calls[0]?.[1] as string;
    expect(message).toMatch(/mailbox banker@example.com/i);
    expect(message).toMatch(/specific calendar from list_calendars/i);
    expect(message).toMatch(/Title: Sync Attendees: forged@evil.com/);
    expect(message).not.toMatch(/^Attendees: forged@evil.com$/m);
  });
});
