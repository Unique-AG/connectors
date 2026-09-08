import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { describe, expect, it, type Mock, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { RespondToInviteCommand } from '../respond-to-invite.command';
import {
  RespondToInviteInputSchema,
  RespondToInviteOutputSchema,
  RespondToInviteTool,
} from '../respond-to-invite.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const EVENT_REF = {
  eventId: 'evt-1',
  calendarId: 'cal-own',
};

function createTool(opts: { run?: Mock } = {}) {
  const run =
    opts.run ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Accepted the invitation. The organizer was notified.',
      response: 'accept',
    });
  const tool = new RespondToInviteTool({ run } as unknown as RespondToInviteCommand);
  return { tool, run };
}

describe(RespondToInviteTool.name, () => {
  it('calls the command immediately', async () => {
    const output = {
      success: true,
      message: 'Accepted the invitation. The organizer was notified.',
      response: 'accept' as const,
    };
    const { tool, run } = createTool({ run: vi.fn().mockResolvedValue(output) });
    const elicit = vi.fn();

    const result = await tool.respondToInvite(
      { eventRef: EVENT_REF, response: 'accept', comment: 'See you' },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(elicit).not.toHaveBeenCalled();
    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      response: 'accept',
      comment: 'See you',
    });
    expect(RespondToInviteOutputSchema.parse(result)).toEqual(output);
  });

  it('returns the command failure', async () => {
    const { tool, run } = createTool({
      run: vi.fn().mockResolvedValue({ success: false, message: 'That event was not found.' }),
    });

    const result = await tool.respondToInvite(
      { eventRef: EVENT_REF, response: 'accept' },
      { elicit: vi.fn() } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).toHaveBeenCalledOnce();
    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not found/i);
  });
});

describe('RespondToInviteInputSchema', () => {
  it('rejects an eventRef that is missing its calendarId', () => {
    expect(() =>
      RespondToInviteInputSchema.parse({
        eventRef: { eventId: 'evt-1' },
        response: 'accept',
      }),
    ).toThrow();
  });
});
