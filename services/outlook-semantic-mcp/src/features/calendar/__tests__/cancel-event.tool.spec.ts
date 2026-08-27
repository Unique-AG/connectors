import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { describe, expect, it, vi } from 'vitest';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CancelEventCommand } from '../cancel-event.command';
import { CancelEventOutputSchema, CancelEventTool } from '../cancel-event.tool';
import { GetCalendarQuery } from '../get-calendar.query';
import { GetCalendarEventQuery } from '../get-calendar-event.query';
import { passthroughCalendarMetrics } from './passthrough-calendar-metrics';

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
    type: 'occurrence' as const,
    seriesMasterId: 'master-1',
    subject: 'Sync',
    start: { dateTime: '2026-08-26T09:00:00', timeZone: 'W. Europe Standard Time' },
    end: { dateTime: '2026-08-26T09:30:00', timeZone: 'W. Europe Standard Time' },
    location: null,
    organizerName: 'Me',
    organizerEmail: 'me@example.com',
    isCancelled: false,
    attendeeCount: 2,
  },
};
const OWN_PRIMARY = {
  success: true,
  message: 'Loaded the calendar.',
  calendar: {
    calendarId: 'cal-own',
    mailbox: 'me@example.com',
    name: 'Calendar',
    isDefaultCalendar: true,
    isOwn: true,
    ownerEmail: 'me@example.com',
    ownerName: 'Me',
    canEdit: true,
  },
};

function createTool(
  opts: {
    get?: ReturnType<typeof vi.fn>;
    getCalendar?: ReturnType<typeof vi.fn>;
    run?: ReturnType<typeof vi.fn>;
    elicit?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const get = opts.get ?? vi.fn().mockResolvedValue(SNAPSHOT);
  const getCalendar = opts.getCalendar ?? vi.fn().mockResolvedValue(OWN_PRIMARY);
  const run =
    opts.run ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Cancelled the event. Attendees were notified.',
    });
  const elicit =
    opts.elicit ??
    vi.fn().mockResolvedValue({
      action: 'accept',
      content: { applyTo: 'thisOccurrence' },
    });
  const tool = new CancelEventTool(
    { run: get } as unknown as GetCalendarEventQuery,
    { run: getCalendar } as unknown as GetCalendarQuery,
    { run } as unknown as CancelEventCommand,
  );
  return { tool, get, getCalendar, run, elicit };
}

describe(CancelEventTool.name, () => {
  it('elicits series scope then cancels this occurrence', async () => {
    const output = { success: true, message: 'Cancelled the event. Attendees were notified.' };
    const { tool, run, elicit } = createTool({ run: vi.fn().mockResolvedValue(output) });

    const result = await tool.cancelEvent(
      { eventRef: EVENT_REF, comment: 'Travel conflict' },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(elicit).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(
        /your primary calendar[\s\S]*Wed 26 Aug 2026, 09:00–09:30 GMT\+2[\s\S]*not a silent delete/i,
      ),
    );
    expect(run).toHaveBeenCalledWith(
      USER_PROFILE_ID,
      expect.objectContaining({
        targetEventId: 'evt-1',
        comment: 'Travel conflict',
        attendeesWereNotified: true,
      }),
    );
    expect(CancelEventOutputSchema.parse(result)).toEqual(output);
  });

  it('does not cancel when the event is already cancelled', async () => {
    const { tool, run, elicit } = createTool({
      get: vi.fn().mockResolvedValue({
        ...SNAPSHOT,
        event: { ...SNAPSHOT.event, isCancelled: true },
      }),
    });

    const result = await tool.cancelEvent(
      { eventRef: EVENT_REF },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
    expect(result.message).toMatch(/already cancelled/i);
  });

  it.each([
    ['the prompt is dismissed', { action: 'cancel' }],
    ['the prompt is declined', { action: 'decline' }],
  ])('does not call the command when %s', async (_label, elicitResult) => {
    const elicit = vi.fn().mockResolvedValue(elicitResult);
    const { tool, run } = createTool({ elicit });

    const result = await tool.cancelEvent(
      { eventRef: EVENT_REF },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
  });

  it('does not cancel when the confirmation prompt times out', async () => {
    const elicit = vi
      .fn()
      .mockRejectedValue(new McpError(ErrorCode.RequestTimeout, 'Request timed out'));
    const { tool, run } = createTool({ elicit });

    const result = await tool.cancelEvent(
      { eventRef: EVENT_REF },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.message).toMatch(/timed out/i);
  });

  it('does not cancel when the client cannot show a confirmation prompt', async () => {
    const elicit = vi.fn().mockRejectedValue(new Error('This client does not support elicitation'));
    const { tool, run } = createTool({ elicit });

    const result = await tool.cancelEvent(
      { eventRef: EVENT_REF },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.message).toMatch(/cannot show a confirmation prompt/i);
  });

  it('issues no Graph request at all when the confirmation is declined', async () => {
    // The other decline tests assert on a mocked command. This one wires the real command to a
    // mocked Graph client, because "the elicitation is the only thing between the model and a
    // cancellation notice in an attendee's inbox" is a claim about HTTP, not about a spy.
    const post = vi.fn().mockResolvedValue({});
    const command = new CancelEventCommand(
      {
        createClientForUser: vi.fn().mockReturnValue({
          api: vi.fn().mockReturnValue({ header: vi.fn().mockReturnThis(), post }),
        }),
      } as unknown as GraphClientFactory,
      {
        run: vi.fn().mockResolvedValue({ id: USER_PROFILE_ID.toString(), email: 'me@example.com' }),
      } as unknown as GetUserProfileQuery,
      passthroughCalendarMetrics() as unknown as CalendarMetricsService,
    );
    const tool = new CancelEventTool(
      { run: vi.fn().mockResolvedValue(SNAPSHOT) } as unknown as GetCalendarEventQuery,
      { run: vi.fn().mockResolvedValue(OWN_PRIMARY) } as unknown as GetCalendarQuery,
      command,
    );
    const elicit = vi.fn().mockResolvedValue({ action: 'cancel' });

    const result = await tool.cancelEvent(
      { eventRef: EVENT_REF },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(post).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
  });
});
