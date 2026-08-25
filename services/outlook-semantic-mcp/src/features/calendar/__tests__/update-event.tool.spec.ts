import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { UpdateEventOutputSchema, UpdateEventTool } from '../update-event.tool';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const EVENT_REF = {
  eventId: 'evt-1',
  calendarId: 'cal-own',
  mailbox: 'me@example.com',
};
const INPUT = { eventRef: EVENT_REF, subject: 'Renamed' };
const OCCURRENCE = {
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
  const get = opts.get ?? vi.fn().mockResolvedValue(OCCURRENCE);
  const run =
    opts.run ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Updated the event. Attendees were notified immediately.',
    });
  const elicit =
    opts.elicit ??
    vi.fn().mockResolvedValue({
      action: 'accept',
      content: { confirmed: true, applyTo: 'entireSeries' },
    });
  const tool = new UpdateEventTool({ run: get } as never, { run } as never);
  return { tool, get, run, elicit };
}

describe(UpdateEventTool.name, () => {
  it('elicits series scope then PATCHes the series master', async () => {
    const output = {
      success: true,
      message: 'Updated the event. Attendees were notified immediately.',
    };
    const { tool, get, run, elicit } = createTool({ run: vi.fn().mockResolvedValue(output) });

    const result = await tool.updateEvent(
      INPUT,
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(get).toHaveBeenCalledWith(USER_PROFILE_ID, { eventRef: EVENT_REF });
    expect(elicit).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(/mailbox me@example.com[\s\S]*entire series/i),
    );
    expect(run).toHaveBeenCalledWith(
      USER_PROFILE_ID,
      expect.objectContaining({
        eventRef: EVENT_REF,
        targetEventId: 'master-1',
        subject: 'Renamed',
        attendeesWereNotified: true,
      }),
    );
    expect(UpdateEventOutputSchema.parse(result)).toEqual(output);
  });

  it('does not call the command when elicitation is cancelled', async () => {
    const { tool, run, elicit } = createTool({
      elicit: vi.fn().mockResolvedValue({ action: 'cancel' }),
    });

    const result = await tool.updateEvent(
      INPUT,
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
  });

  it('returns the query failure without eliciting', async () => {
    const { tool, run, elicit } = createTool({
      get: vi.fn().mockResolvedValue({ success: false, message: 'That event was not found.' }),
    });

    const result = await tool.updateEvent(
      INPUT,
      { elicit } as never,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
    );

    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
    expect(result.message).toMatch(/not found/i);
  });

  it('rejects an update with no fields to change', async () => {
    const { tool, get, elicit } = createTool();

    await expect(
      tool.updateEvent(
        { eventRef: EVENT_REF },
        { elicit } as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/at least one field/i);
    expect(get).not.toHaveBeenCalled();
  });

  it('rejects a whitespace-only subject', async () => {
    const { tool, get, elicit } = createTool();

    await expect(
      tool.updateEvent(
        { eventRef: EVENT_REF, subject: '   ' },
        { elicit } as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow();
    expect(get).not.toHaveBeenCalled();
  });

  it('rejects isOnlineMeeting false as the only change', async () => {
    const { tool, get, elicit } = createTool();

    await expect(
      tool.updateEvent(
        { eventRef: EVENT_REF, isOnlineMeeting: false } as never,
        { elicit } as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow();
    expect(get).not.toHaveBeenCalled();
  });

  it('rejects a start-only timestamp that is not a real instant', async () => {
    const { tool, get, elicit } = createTool();

    await expect(
      tool.updateEvent(
        { eventRef: EVENT_REF, startDateTime: 'not-a-date+02:00' },
        { elicit } as never,
        { user: { userProfileId: USER_PROFILE_ID.toString() } } as never,
      ),
    ).rejects.toThrow(/offset-bearing timestamp/i);
    expect(get).not.toHaveBeenCalled();
  });
});
