import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CancelEventOutputSchema, CancelEventTool } from '../cancel-event.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const EVENT_REF = {
  eventId: 'evt-1',
  calendarId: 'cal-own',
  accessPath: 'ownMailbox' as const,
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
      message: 'Cancelled the event. Attendees were notified.',
    });
  const elicit =
    opts.elicit ??
    vi.fn().mockResolvedValue({
      action: 'accept',
      content: { confirmed: true, applyTo: 'thisOccurrence' },
    });
  const tool = new CancelEventTool({ run: get } as never, { run } as never);
  return { tool, get, run, elicit };
}

describe(CancelEventTool.name, () => {
  it('elicits series scope then cancels this occurrence', async () => {
    const output = { success: true, message: 'Cancelled the event. Attendees were notified.' };
    const { tool, run, elicit } = createTool({ run: vi.fn().mockResolvedValue(output) });

    const result = await tool.cancelEvent(
      { eventRef: EVENT_REF, comment: 'Travel conflict' },
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(elicit).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(/mailbox me@example.com[\s\S]*not a silent delete/i),
    );
    expect(run).toHaveBeenCalledWith(
      USER_PROFILE_ID,
      expect.objectContaining({
        targetEventId: 'evt-1',
        comment: 'Travel conflict',
        notifyAttendees: true,
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
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
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
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
  });
});
