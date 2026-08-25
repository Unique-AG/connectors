import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { RespondToInviteOutputSchema, RespondToInviteTool } from '../respond-to-invite.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const EVENT_REF = {
  eventId: 'evt-1',
  calendarId: 'cal-own',
  accessPath: 'ownMailbox' as const,
  mailbox: 'me@example.com',
};

function createTool(
  opts: { run?: ReturnType<typeof vi.fn>; elicit?: ReturnType<typeof vi.fn> } = {},
) {
  const run =
    opts.run ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Accepted the invitation. The organizer was notified.',
      response: 'accept',
    });
  const elicit =
    opts.elicit ?? vi.fn().mockResolvedValue({ action: 'accept', content: { confirmed: true } });
  const tool = new RespondToInviteTool({ run } as never);
  return { tool, run, elicit };
}

describe(RespondToInviteTool.name, () => {
  it('elicits confirmation and then calls the command', async () => {
    const output = {
      success: true,
      message: 'Accepted the invitation. The organizer was notified.',
      response: 'accept' as const,
    };
    const { tool, run, elicit } = createTool({ run: vi.fn().mockResolvedValue(output) });

    const result = await tool.respondToInvite(
      { eventRef: EVENT_REF, response: 'accept', comment: 'See you' },
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(elicit).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(/accept this invitation/i),
    );
    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      response: 'accept',
      comment: 'See you',
    });
    expect(RespondToInviteOutputSchema.parse(result)).toEqual(output);
  });

  it('does not call the command when elicitation is cancelled', async () => {
    const { tool, run, elicit } = createTool({
      elicit: vi.fn().mockResolvedValue({ action: 'cancel' }),
    });

    const result = await tool.respondToInvite(
      { eventRef: EVENT_REF, response: 'decline' },
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.message).toMatch(/cancelled/i);
  });

  it('does not call the command when the user unchecks confirm', async () => {
    const { tool, run, elicit } = createTool({
      elicit: vi.fn().mockResolvedValue({ action: 'accept', content: { confirmed: false } }),
    });

    const result = await tool.respondToInvite(
      { eventRef: EVENT_REF, response: 'tentativelyAccept' },
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
  });

  it('rejects an eventRef mailbox that is not an SMTP address', async () => {
    const { tool, run, elicit } = createTool();

    await expect(
      tool.respondToInvite(
        {
          eventRef: { ...EVENT_REF, mailbox: 'not/an/email' },
          response: 'accept',
        },
        { elicit } as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/SMTP/i);
    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
  });
});
