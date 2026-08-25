import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { RespondToInviteCommand } from '../respond-to-invite.command';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const EVENT_REF = {
  eventId: 'evt-1',
  calendarId: 'cal-own',
  accessPath: 'ownMailbox' as const,
  mailbox: OWN_EMAIL,
};
const PATH = `/users/${OWN_EMAIL}/calendars/cal-own/events/evt-1/accept`;
const DELEGATED_PATH = '/users/banker@example.com/calendars/cal-banker/events/evt-2/decline';

function makeGraphError(statusCode: number, code: string, message = 'Access denied'): GraphError {
  const err = new GraphError(statusCode, message);
  err.code = code;
  return err;
}

function createCommand(opts: { post?: ReturnType<typeof vi.fn>; email?: string } = {}) {
  const post = opts.post ?? vi.fn().mockResolvedValue(undefined);
  const request = {
    header: vi.fn().mockReturnThis(),
    post,
  };
  const api = vi.fn().mockReturnValue(request);
  const command = new RespondToInviteCommand(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as never,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: opts.email ?? OWN_EMAIL,
        source: 'oauth',
      }),
    } as never,
  );
  return { command, api, request, post };
}

describe(RespondToInviteCommand.name, () => {
  it('POSTs accept on the event path and reports the organizer was notified', async () => {
    const { command, api, request, post } = createCommand();

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      response: 'accept',
      comment: 'See you there',
    });

    expect(api).toHaveBeenCalledWith(PATH);
    expect(request.header).toHaveBeenCalledWith('Prefer', 'IdType="ImmutableId"');
    expect(post).toHaveBeenCalledWith({ sendResponse: true, comment: 'See you there' });
    expect(result).toEqual({
      success: true,
      message: 'Accepted the invitation. The organizer was notified.',
      response: 'accept',
    });
  });

  it('omits an empty comment from the Graph body', async () => {
    const { command, post } = createCommand();

    await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      response: 'accept',
      comment: '   ',
    });

    expect(post).toHaveBeenCalledWith({ sendResponse: true });
  });

  it('returns consentRequired when the caller mailbox is denied', async () => {
    const { command } = createCommand({
      post: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      response: 'accept',
    });

    expect(result.success).toBe(false);
    expect(result.consentRequired).toBe(true);
    expect(result.message).toMatch(/re-authorization/i);
  });

  it('does not ask for consent when a delegated mailbox is denied', async () => {
    const { command, api } = createCommand({
      post: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: {
        eventId: 'evt-2',
        calendarId: 'cal-banker',
        accessPath: 'ownerMailbox',
        mailbox: 'banker@example.com',
      },
      response: 'decline',
    });

    expect(api).toHaveBeenCalledWith(DELEGATED_PATH);
    expect(result.success).toBe(false);
    expect(result.consentRequired).toBeUndefined();
    expect(result.message).toMatch(/banker@example.com/);
  });

  it('returns a not-found message on 404', async () => {
    const { command } = createCommand({
      post: vi.fn().mockRejectedValue(makeGraphError(404, 'ErrorItemNotFound', 'Not found')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      response: 'tentativelyAccept',
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not found/i);
  });
});
