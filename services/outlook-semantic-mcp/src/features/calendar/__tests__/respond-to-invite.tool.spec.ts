import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { GetCalendarEventQuery } from '../get-calendar-event.query';
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
  mailbox: 'me@example.com',
};

const SNAPSHOT = {
  success: true,
  message: 'Loaded the event.',
  event: {
    eventId: 'evt-1',
    calendarId: 'cal-own',
    mailbox: 'me@example.com',
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

function createTool(
  opts: {
    get?: ReturnType<typeof vi.fn>;
    run?: ReturnType<typeof vi.fn>;
    elicit?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const get = opts.get ?? vi.fn().mockResolvedValue(SNAPSHOT);
  const run =
    opts.run ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Accepted the invitation. The organizer was notified.',
      response: 'accept',
    });
  const elicit = opts.elicit ?? vi.fn().mockResolvedValue({ action: 'accept', content: {} });
  const tool = new RespondToInviteTool(
    { run: get } as unknown as GetCalendarEventQuery,
    { run } as unknown as RespondToInviteCommand,
  );
  return { tool, get, run, elicit };
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
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(elicit).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(
        /accept this invitation[\s\S]*Weekly sync[\s\S]*Wed 26 Aug 2026, 09:00–09:30 GMT\+2[\s\S]*Alex Rivera/i,
      ),
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
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.message).toMatch(/cancelled/i);
  });

  it('does not respond when the confirmation prompt times out', async () => {
    const { tool, run, elicit } = createTool({
      elicit: vi
        .fn()
        .mockRejectedValue(new McpError(ErrorCode.RequestTimeout, 'Request timed out')),
    });

    const result = await tool.respondToInvite(
      { eventRef: EVENT_REF, response: 'accept' },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.message).toMatch(/timed out/i);
  });

  it('returns the query failure without eliciting', async () => {
    const { tool, run, elicit } = createTool({
      get: vi.fn().mockResolvedValue({ success: false, message: 'That event was not found.' }),
    });

    const result = await tool.respondToInvite(
      { eventRef: EVENT_REF, response: 'accept' },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
    expect(result.message).toMatch(/not found/i);
  });
});

describe('RespondToInviteInputSchema', () => {
  it('rejects an eventRef mailbox that is not an SMTP address', () => {
    expect(() =>
      RespondToInviteInputSchema.parse({
        eventRef: { ...EVENT_REF, mailbox: 'not/an/email' },
        response: 'accept',
      }),
    ).toThrow(/SMTP/i);
  });
});
