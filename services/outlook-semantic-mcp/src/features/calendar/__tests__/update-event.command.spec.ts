import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { UpdateEventCommand } from '../update-event.command';
import { graphEventBody } from '../utils/graph-event-body';
import { passthroughCalendarMetrics } from './passthrough-calendar-metrics';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const EVENT_REF = {
  eventId: 'evt-1',
  calendarId: 'cal-own',
  mailbox: OWN_EMAIL,
};
const PATH = `/users/${OWN_EMAIL}/calendars/cal-own/events/master-1`;
const PREFER = 'outlook.timezone="W. Europe Standard Time", IdType="ImmutableId"';

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

const TEAMS_BLOB = `<div style="width:100%; height:20px"><span style="white-space:nowrap; color:gray; opacity:.36">________________________________________________________________________________</span>
</div>
<div class="me-email-text">Join Microsoft Teams Meeting</div>`;
const GET_BODY_PREFER =
  'outlook.timezone="W. Europe Standard Time", IdType="ImmutableId", outlook.body-content-type="html"';

function createCommand(
  opts: { patch?: ReturnType<typeof vi.fn>; get?: ReturnType<typeof vi.fn> } = {},
) {
  const patch =
    opts.patch ??
    vi.fn().mockResolvedValue({
      id: 'master-1',
      subject: 'Renamed',
      start: { dateTime: '2026-08-26T10:00:00', timeZone: 'W. Europe Standard Time' },
      end: { dateTime: '2026-08-26T10:30:00', timeZone: 'W. Europe Standard Time' },
      location: { displayName: 'Room B' },
      webLink: 'https://outlook.example/evt',
    });
  const get = opts.get ?? vi.fn().mockResolvedValue({ body: { content: '', contentType: 'html' } });
  const request = {
    header: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    patch,
    get,
  };
  const api = vi.fn().mockReturnValue(request);
  const command = new UpdateEventCommand(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as unknown as GraphClientFactory,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: OWN_EMAIL,
        source: 'oauth',
      }),
    } as unknown as GetUserProfileQuery,
    {
      run: vi.fn().mockResolvedValue({
        ianaTimeZone: 'Europe/Zurich',
        outlookTimeZone: 'W. Europe Standard Time',
        notes: [],
      }),
    } as unknown as ResolveMailboxTimezoneQuery,
    passthroughCalendarMetrics() as unknown as CalendarMetricsService,
  );
  return { command, api, request, patch, get };
}

describe(UpdateEventCommand.name, () => {
  it('PATCHes the target event and reports attendees were notified', async () => {
    const { command, api, request, patch } = createCommand();

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      targetEventId: 'master-1',
      subject: 'Renamed',
      startDateTime: '2026-08-26T10:00:00+02:00',
      endDateTime: '2026-08-26T10:30:00+02:00',
      attendeesWereNotified: true,
    });

    expect(api).toHaveBeenCalledWith(PATH);
    expect(request.header).toHaveBeenCalledWith('Prefer', PREFER);
    expect(patch).toHaveBeenCalledWith({
      subject: 'Renamed',
      start: { dateTime: '2026-08-26T10:00:00', timeZone: 'W. Europe Standard Time' },
      end: { dateTime: '2026-08-26T10:30:00', timeZone: 'W. Europe Standard Time' },
    });
    expect(result.success).toBe(true);
    expect(result.message).toMatch(/notified immediately/i);
    expect(result.eventRef?.eventId).toBe('master-1');
    expect(request.get).not.toHaveBeenCalled();
  });

  it("PATCHes the agent HTML unchanged and keeps Microsoft's Teams HTML in the document", async () => {
    const existing = `<html><body><p>Old</p>${TEAMS_BLOB}</body></html>`;
    const { command, request, patch, get } = createCommand({
      get: vi.fn().mockResolvedValue({ body: { content: existing, contentType: 'html' } }),
    });
    const body = '<p>Hello <strong>world</strong></p>';

    await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      targetEventId: 'master-1',
      body,
      attendeesWereNotified: false,
    });

    expect(request.select).toHaveBeenCalledWith('body');
    expect(request.header).toHaveBeenCalledWith('Prefer', GET_BODY_PREFER);
    expect(get).toHaveBeenCalledOnce();
    expect(patch).toHaveBeenCalledWith({
      body: graphEventBody(body, existing),
    });
  });

  it('returns a not-found message when the body GET is 404', async () => {
    const { command, patch } = createCommand({
      get: vi.fn().mockRejectedValue(makeGraphError(404, 'ErrorItemNotFound')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      targetEventId: 'master-1',
      body: 'Hello **world**',
      attendeesWereNotified: false,
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not found/i);
    expect(patch).not.toHaveBeenCalled();
  });

  it('returns a not-found message on 404', async () => {
    const { command } = createCommand({
      patch: vi.fn().mockRejectedValue(makeGraphError(404, 'ErrorItemNotFound')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      targetEventId: 'master-1',
      subject: 'Renamed',
      attendeesWereNotified: false,
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not found/i);
  });

  it('returns success false when Graph rejects the body', async () => {
    const { command } = createCommand({
      patch: vi.fn().mockRejectedValue(makeGraphError(400, 'ErrorInvalidRequest')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      targetEventId: 'master-1',
      subject: 'Renamed',
      attendeesWereNotified: false,
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/rejected/i);
  });
});
