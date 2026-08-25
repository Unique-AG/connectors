import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CreateEventCommand } from '../create-event.command';
import { passthroughCalendarMetrics } from './passthrough-calendar-metrics';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const DEFAULT_TZ = {
  ianaTimeZone: 'Europe/Zurich',
  outlookTimeZone: 'W. Europe Standard Time',
  notes: [],
};
const CREATE_PATH = `/users/${OWN_EMAIL}/calendars/cal-own/events`;
const PREFER = 'outlook.timezone="W. Europe Standard Time", IdType="ImmutableId"';

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

function createdEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: 'evt-1',
    subject: 'Sync',
    start: { dateTime: '2026-08-26T09:00:00', timeZone: 'W. Europe Standard Time' },
    end: { dateTime: '2026-08-26T09:30:00', timeZone: 'W. Europe Standard Time' },
    location: { displayName: 'Room A' },
    webLink: 'https://outlook.example/evt-1',
    onlineMeeting: { joinUrl: 'https://teams.example/join' },
    ...overrides,
  };
}

function createCommand(
  opts: { post?: ReturnType<typeof vi.fn>; get?: ReturnType<typeof vi.fn> } = {},
) {
  const post = opts.post ?? vi.fn().mockResolvedValue(createdEvent());
  const get = opts.get ?? vi.fn().mockResolvedValue({ id: 'cal-own' });
  const request = {
    header: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    post,
    get,
  };
  const api = vi.fn().mockReturnValue(request);
  const command = new CreateEventCommand(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as never,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: OWN_EMAIL,
        source: 'oauth',
      }),
    } as never,
    { run: vi.fn().mockResolvedValue(DEFAULT_TZ) } as never,
    passthroughCalendarMetrics() as never,
  );
  return { command, api, request, post, get };
}

describe(CreateEventCommand.name, () => {
  it('POSTs the event with transactionId and immutable IDs', async () => {
    const { command, api, request, post, get } = createCommand();

    const result = await command.run(USER_PROFILE_ID, {
      subject: 'Sync',
      startDateTime: '2026-08-26T09:00:00+02:00',
      endDateTime: '2026-08-26T09:30:00+02:00',
      attendees: ['alex@example.com'],
      location: 'Room A',
      isOnlineMeeting: true,
      calendarRef: { calendarId: 'cal-own', mailbox: OWN_EMAIL },
      transactionId: 'abc123abc123abc123abc123abc123ab',
    });

    expect(api).toHaveBeenCalledWith(CREATE_PATH);
    expect(request.header).toHaveBeenCalledWith('Prefer', PREFER);
    expect(post).toHaveBeenCalledWith({
      subject: 'Sync',
      start: { dateTime: '2026-08-26T09:00:00', timeZone: 'W. Europe Standard Time' },
      end: { dateTime: '2026-08-26T09:30:00', timeZone: 'W. Europe Standard Time' },
      transactionId: 'abc123abc123abc123abc123abc123ab',
      location: { displayName: 'Room A' },
      attendees: [{ type: 'required', emailAddress: { address: 'alex@example.com' } }],
      isOnlineMeeting: true,
      onlineMeetingProvider: 'teamsForBusiness',
    });
    expect(result.success).toBe(true);
    expect(result.message).toMatch(/sent invitations immediately/i);
    expect(result.eventRef).toEqual({
      eventId: 'evt-1',
      calendarId: 'cal-own',
      mailbox: OWN_EMAIL,
    });
    expect(result.joinUrl).toBe('https://teams.example/join');
    expect(result.transactionId).toBe('abc123abc123abc123abc123abc123ab');
  });

  it('uses the given calendarId and skips the default-calendar GET', async () => {
    const { command, api, get } = createCommand();

    await command.run(USER_PROFILE_ID, {
      subject: 'Sync',
      startDateTime: '2026-08-26T09:00:00+02:00',
      endDateTime: '2026-08-26T09:30:00+02:00',
      calendarRef: { calendarId: 'cal-banker', mailbox: 'banker@example.com' },
      transactionId: 'abc123abc123abc123abc123abc123ab',
    });

    expect(get).not.toHaveBeenCalled();
    expect(api).toHaveBeenCalledWith('/users/banker@example.com/calendars/cal-banker/events');
  });

  it('returns consentRequired when the caller mailbox is denied', async () => {
    const { command } = createCommand({
      post: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
      get: vi.fn().mockResolvedValue({ id: 'cal-own' }),
    });

    const result = await command.run(USER_PROFILE_ID, {
      subject: 'Sync',
      startDateTime: '2026-08-26T09:00:00+02:00',
      endDateTime: '2026-08-26T09:30:00+02:00',
      calendarRef: { calendarId: 'cal-own', mailbox: OWN_EMAIL },
      transactionId: 'abc123abc123abc123abc123abc123ab',
    });

    expect(result.success).toBe(false);
    expect(result.consentRequired).toBe(true);
  });

  it('does not ask for consent when a delegated mailbox is denied', async () => {
    const { command } = createCommand({
      post: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      subject: 'Sync',
      startDateTime: '2026-08-26T09:00:00+02:00',
      endDateTime: '2026-08-26T09:30:00+02:00',
      calendarRef: { calendarId: 'cal-banker', mailbox: 'banker@example.com' },
      transactionId: 'abc123abc123abc123abc123abc123ab',
    });

    expect(result.success).toBe(false);
    expect(result.consentRequired).toBeUndefined();
    expect(result.message).toMatch(/banker@example.com/);
  });

  it('returns success false when the calendar is not found', async () => {
    const { command } = createCommand({
      post: vi.fn().mockRejectedValue(makeGraphError(404, 'ErrorItemNotFound')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      subject: 'Sync',
      startDateTime: '2026-08-26T09:00:00+02:00',
      endDateTime: '2026-08-26T09:30:00+02:00',
      calendarRef: { calendarId: 'missing', mailbox: 'banker@example.com' },
      transactionId: 'abc123abc123abc123abc123abc123ab',
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not found/i);
    expect(result.transactionId).toBe('abc123abc123abc123abc123abc123ab');
  });

  it('returns success false when Graph rejects the event body', async () => {
    const { command } = createCommand({
      post: vi.fn().mockRejectedValue(makeGraphError(400, 'ErrorInvalidRequest')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      subject: 'Sync',
      startDateTime: '2026-08-26T09:00:00+02:00',
      endDateTime: '2026-08-26T09:30:00+02:00',
      calendarRef: { calendarId: 'cal-own', mailbox: 'me@example.com' },
      transactionId: 'abc123abc123abc123abc123abc123ab',
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/rejected/i);
  });
});
