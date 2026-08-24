import { describe, expect, it } from 'vitest';
import { templateEndpoint, UNKNOWN_ENDPOINT } from './endpoint-template';

const GRAPH = 'https://graph.microsoft.com';

// A 1:1 chat thread id embeds both participants' Entra object ids, which is the
// reason this templating exists at all.
const ONE_ON_ONE =
  '19:8a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9_1f2e3d4c-5b6a-7089-9182-b3c4d5e6f7a8@unq.gbl.spaces';
const GROUP_CHAT = '19:bdeff6bfed7f4b159cdf7fdd61aeacaa@thread.v2';
const CHANNEL = '19:TWLPKo8lD4v8zDxyw4FnDYY-ovnBJG5CSjmrHUAoOz41@thread.tacv2';
const TEAM = '02bd9fd6-8f93-4758-87c3-1fb73740a315';
const MESSAGE = '1657782060227';

describe('templateEndpoint', () => {
  it('templates a one-to-one chat message so no participant id survives', () => {
    const label = templateEndpoint(`${GRAPH}/v1.0/chats/${ONE_ON_ONE}/messages/${MESSAGE}`);

    expect(label).toBe('/chats/:chatId/messages/:messageId');
    expect(label).not.toContain('unq.gbl.spaces');
    expect(label).not.toContain('8a1b2c3d');
  });

  it('templates a group chat message list', () => {
    expect(templateEndpoint(`${GRAPH}/v1.0/chats/${GROUP_CHAT}/messages`)).toBe(
      '/chats/:chatId/messages',
    );
  });

  // A Teams message id is a 13-digit epoch value, so a length-based heuristic
  // leaves it in the label.
  it('templates the numeric message id, not only the thread id', () => {
    expect(templateEndpoint(`${GRAPH}/v1.0/chats/${GROUP_CHAT}/messages/${MESSAGE}`)).not.toContain(
      MESSAGE,
    );
  });

  it('templates a channel message', () => {
    expect(
      templateEndpoint(`${GRAPH}/v1.0/teams/${TEAM}/channels/${CHANNEL}/messages/${MESSAGE}`),
    ).toBe('/teams/:teamId/channels/:channelId/messages/:messageId');
  });

  it('templates a channel list', () => {
    expect(templateEndpoint(`${GRAPH}/v1.0/teams/${TEAM}/channels`)).toBe(
      '/teams/:teamId/channels',
    );
  });

  it('keeps a collection route that carries no id intact', () => {
    expect(templateEndpoint(`${GRAPH}/v1.0/me/chats`)).toBe('/me/chats');
    expect(templateEndpoint(`${GRAPH}/v1.0/me/joinedTeams`)).toBe('/me/joinedTeams');
    expect(templateEndpoint(`${GRAPH}/v1.0/search/query`)).toBe('/search/query');
    expect(templateEndpoint(`${GRAPH}/v1.0/subscriptions`)).toBe('/subscriptions');
  });

  it('templates a subscription id', () => {
    expect(templateEndpoint(`${GRAPH}/v1.0/subscriptions/${TEAM}`)).toBe(
      '/subscriptions/:subscriptionId',
    );
  });

  it('templates the delegated meeting transcript routes', () => {
    expect(templateEndpoint(`${GRAPH}/v1.0/me/onlineMeetings/MSo${TEAM}/transcripts`)).toBe(
      '/me/onlineMeetings/:meetingId/transcripts',
    );
    expect(
      templateEndpoint(`${GRAPH}/v1.0/me/onlineMeetings/MSo${TEAM}/transcripts/abc-123/content`),
    ).toBe('/me/onlineMeetings/:meetingId/transcripts/:transcriptId/content');
  });

  it('templates the webhook meeting routes, keeping the user id out of the label', () => {
    const label = templateEndpoint(
      `${GRAPH}/v1.0/users/${TEAM}/onlineMeetings/MSo${TEAM}/recordings/rec-1/content`,
    );

    expect(label).toBe('/users/:userId/onlineMeetings/:meetingId/recordings/:recordingId/content');
    expect(label).not.toContain(TEAM);
  });

  it('strips the beta version prefix as well as v1.0', () => {
    expect(templateEndpoint(`${GRAPH}/beta/search/query`)).toBe('/search/query');
  });

  it('ignores a query string', () => {
    expect(templateEndpoint(`${GRAPH}/v1.0/me/chats?$top=50&$expand=members`)).toBe('/me/chats');
  });

  it('reports an unrecognised route as unknown rather than leaking its segments', () => {
    expect(templateEndpoint(`${GRAPH}/v1.0/drives/${TEAM}/items/${ONE_ON_ONE}`)).toBe(
      UNKNOWN_ENDPOINT,
    );
  });

  it('reports a malformed url as unknown', () => {
    expect(templateEndpoint('not-a-url')).toBe(UNKNOWN_ENDPOINT);
  });

  it('never returns a label containing a chat thread id for any route it knows', () => {
    const urls = [
      `${GRAPH}/v1.0/chats/${ONE_ON_ONE}/messages`,
      `${GRAPH}/v1.0/chats/${ONE_ON_ONE}/messages/${MESSAGE}`,
      `${GRAPH}/v1.0/teams/${TEAM}/channels/${CHANNEL}/messages`,
    ];

    for (const url of urls) {
      expect(templateEndpoint(url)).not.toMatch(/19:|@unq|@thread/);
    }
  });
});
