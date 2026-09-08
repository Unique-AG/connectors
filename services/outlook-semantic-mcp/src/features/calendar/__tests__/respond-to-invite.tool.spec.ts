import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
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

const SNAPSHOT = {
  success: true,
  message: 'Loaded the event.',
  event: {
    eventId: 'evt-1',
    calendarId: 'cal-own',
    type: 'singleInstance' as const,
    seriesMasterId: null,
    subject: 'Weekly sync',
    start: { dateTime: '2026-08-26T09:00:00', timeZone: 'W. Europe Standard Time' },
    end: { dateTime: '2026-08-26T09:30:00', timeZone: 'W. Europe Standard Time' },
    location: null,
    organizerName: 'Alex Rivera',
    organizerEmail: 'alex@example.com',
    isCancelled: false,
    attendeeCount: 2,
  },
};

function createTool(opts: { get?: Mock; run?: Mock; elicit?: Mock } = {}) {
  const get = opts.get ?? vi.fn().mockResolvedValue(SNAPSHOT);
  const run =
    opts.run ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Accepted the invitation. The organizer was notified.',
      response: 'accept',
    });
  const tool = new RespondToInviteTool({ run: commandRun } as unknown as RespondToInviteCommand);
  return { tool, run: commandRun };
}

describe(RespondToInviteTool.name, () => {
  it('calls the command immediately', async () => {
    const output = {
      success: true,
      message: 'Accepted the invitation. The organizer was notified.',
      response: 'accept' as const,
    };
    const { tool, run } = createTool(vi.fn().mockResolvedValue(output));
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
    const { tool, run } = createTool(
      vi.fn().mockResolvedValue({ success: false, message: 'That event was not found.' }),
    );

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
