import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CancelEventCommand } from '../cancel-event.command';
import { CancelEventOutputSchema, CancelEventTool } from '../cancel-event.tool';
import { GetCalendarQuery } from '../get-calendar.query';
import { GetCalendarEventQuery } from '../get-calendar-event.query';

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
      content: { confirmed: true, applyTo: 'thisOccurrence' },
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
      expect.stringMatching(/your primary calendar[\s\S]*not a silent delete/i),
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

  it('does not call the command when elicitation is declined', async () => {
    const elicit = vi.fn().mockResolvedValue({ action: 'accept', content: { confirmed: false } });
    const { tool, run } = createTool({ elicit });

    const result = await tool.cancelEvent(
      { eventRef: EVENT_REF },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
  });
});
