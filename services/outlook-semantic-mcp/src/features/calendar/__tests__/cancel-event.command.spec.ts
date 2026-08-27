import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CancelEventCommand } from '../cancel-event.command';
import { passthroughCalendarMetrics } from './passthrough-calendar-metrics';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const EVENT_REF = {
  eventId: 'evt-1',
  calendarId: 'cal-own',
};
const PATH = `/me/calendars/cal-own/events/evt-1/cancel`;

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

function createCommand(opts: { post?: ReturnType<typeof vi.fn> } = {}) {
  const post = opts.post ?? vi.fn().mockResolvedValue(undefined);
  const request = {
    header: vi.fn().mockReturnThis(),
    post,
  };
  const api = vi.fn().mockReturnValue(request);
  const command = new CancelEventCommand(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as unknown as GraphClientFactory,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: OWN_EMAIL,
        source: 'oauth',
      }),
    } as unknown as GetUserProfileQuery,
    passthroughCalendarMetrics() as unknown as CalendarMetricsService,
  );
  return { command, api, request, post };
}

describe(CancelEventCommand.name, () => {
  it('POSTs cancel with ImmutableId and an optional comment', async () => {
    const { command, api, request, post } = createCommand();

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      targetEventId: 'evt-1',
      comment: 'Travel conflict',
      attendeesWereNotified: true,
    });

    expect(api).toHaveBeenCalledWith(PATH);
    expect(request.header).toHaveBeenCalledWith('Prefer', 'IdType="ImmutableId"');
    expect(post).toHaveBeenCalledWith({ comment: 'Travel conflict' });
    expect(result.success).toBe(true);
    expect(result.message).toMatch(/attendees were notified/i);
  });

  it('does not DELETE the event', async () => {
    const { command, request } = createCommand();

    await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      targetEventId: 'evt-1',
      attendeesWereNotified: false,
    });

    expect(request).not.toHaveProperty('delete');
  });

  it('returns a not-found message on 404', async () => {
    const { command } = createCommand({
      post: vi.fn().mockRejectedValue(makeGraphError(404, 'ErrorItemNotFound')),
    });

    const result = await command.run(USER_PROFILE_ID, {
      eventRef: EVENT_REF,
      targetEventId: 'evt-1',
      attendeesWereNotified: false,
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/not found/i);
  });
});
