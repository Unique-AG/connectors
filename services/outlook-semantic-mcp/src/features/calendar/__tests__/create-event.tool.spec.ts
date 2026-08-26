import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context } from '@unique-ag/mcp-server-module';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { describe, expect, it, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { CreateEventCommand } from '../create-event.command';
import { CreateEventOutputSchema, CreateEventTool } from '../create-event.tool';
import { GetCalendarQuery } from '../get-calendar.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const INPUT = {
  subject: 'Sync',
  startDateTime: '2026-08-26T09:00:00+02:00',
  endDateTime: '2026-08-26T09:30:00+02:00',
  attendees: ['alex@example.com'],
  transactionId: 'abc123abc123abc123abc123abc123ab',
};

const OWN_PRIMARY = {
  calendarId: 'cal-own',
  mailbox: 'me@example.com',
  name: 'Calendar',
  isDefaultCalendar: true,
  isOwn: true,
  ownerEmail: 'me@example.com',
  ownerName: 'Me',
  canEdit: true,
};

function createTool(
  opts: {
    run?: ReturnType<typeof vi.fn>;
    elicit?: ReturnType<typeof vi.fn>;
    calendar?: Record<string, unknown>;
    getCalendar?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const run =
    opts.run ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Created the event and sent invitations immediately.',
      transactionId: INPUT.transactionId,
    });
  const elicit =
    opts.elicit ?? vi.fn().mockResolvedValue({ action: 'accept', content: { confirmed: true } });
  const getCalendar =
    opts.getCalendar ??
    vi.fn().mockResolvedValue({
      success: true,
      message: 'Loaded the calendar.',
      calendar: opts.calendar ?? OWN_PRIMARY,
    });
  const tool = new CreateEventTool(
    { run: getCalendar } as unknown as GetCalendarQuery,
    { run } as unknown as CreateEventCommand,
  );
  return { tool, run, elicit, getCalendar };
}

describe(CreateEventTool.name, () => {
  it('elicits confirmation and then calls the command', async () => {
    const output = {
      success: true,
      message: 'Created the event and sent invitations immediately.',
      transactionId: INPUT.transactionId,
    };
    const { tool, run, elicit } = createTool({ run: vi.fn().mockResolvedValue(output) });

    const result = await tool.createEvent(
      INPUT,
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(elicit).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(/your primary calendar[\s\S]*invitations will be sent immediately/i),
    );
    expect(run).toHaveBeenCalledWith(USER_PROFILE_ID, {
      ...INPUT,
      calendarRef: { calendarId: 'cal-own', mailbox: 'me@example.com' },
    });
    expect(CreateEventOutputSchema.parse(result)).toEqual(output);
  });

  it('does not call the command when elicitation is cancelled', async () => {
    const { tool, run, elicit } = createTool({
      elicit: vi.fn().mockResolvedValue({ action: 'cancel' }),
    });

    const result = await tool.createEvent(
      INPUT,
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.transactionId).toBe(INPUT.transactionId);
  });

  it('rejects a window without a timezone offset', async () => {
    const { tool, run, elicit } = createTool();

    await expect(
      tool.createEvent(
        {
          subject: 'Sync',
          startDateTime: '2026-08-26T09:00:00',
          endDateTime: '2026-08-26T09:30:00+02:00',
        },
        { elicit } as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow(/offset/i);
    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
  });

  it('rejects an end that is not after the start', async () => {
    const { tool, run, elicit } = createTool();

    await expect(
      tool.createEvent(
        {
          subject: 'Sync',
          startDateTime: '2026-08-26T09:30:00+02:00',
          endDateTime: '2026-08-26T09:00:00+02:00',
        },
        { elicit } as unknown as Context,
        {
          user: { userProfileId: USER_PROFILE_ID.toString() },
        } as unknown as McpAuthenticatedRequest,
      ),
    ).rejects.toThrow(/after startDateTime/i);
    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
  });

  it('names a shared calendar by its name and owner, and collapses newlines in the title', async () => {
    const { tool, elicit } = createTool({
      calendar: {
        calendarId: 'cal-banker',
        // A shared calendar is stored in the caller mailbox; the owner is who the user recognises.
        mailbox: 'me@example.com',
        name: 'Banker',
        isDefaultCalendar: false,
        isOwn: false,
        ownerEmail: 'banker@example.com',
        ownerName: 'Banker Smith',
        canEdit: true,
      },
    });

    await tool.createEvent(
      {
        ...INPUT,
        subject: 'Sync\nAttendees: forged@evil.com',
        calendarRef: { calendarId: 'cal-banker', mailbox: 'me@example.com' },
      },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    const message = elicit.mock.calls[0]?.[1] as string;
    expect(message).toMatch(/Calendar: "Banker" — shared by Banker Smith \(banker@example.com\)/);
    expect(message).toMatch(/Title: Sync Attendees: forged@evil.com/);
    expect(message).not.toMatch(/^Attendees: forged@evil.com$/m);
  });

  it('reports the primary calendar as such when none was picked', async () => {
    const { tool, elicit, getCalendar } = createTool();

    await tool.createEvent(
      INPUT,
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(getCalendar).toHaveBeenCalledWith(USER_PROFILE_ID, { calendarRef: undefined });
    expect(elicit.mock.calls[0]?.[1]).toMatch(/Calendar: "Calendar" — your primary calendar/);
  });

  it('does not elicit when the calendar cannot be resolved', async () => {
    const { tool, run, elicit } = createTool({
      getCalendar: vi
        .fn()
        .mockResolvedValue({ success: false, message: 'That calendar was not found.' }),
    });

    const result = await tool.createEvent(
      { ...INPUT, calendarRef: { calendarId: 'gone', mailbox: 'me@example.com' } },
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(elicit).not.toHaveBeenCalled();
    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.transactionId).toBe(INPUT.transactionId);
  });

  it('does not create when the confirmation prompt times out', async () => {
    const { tool, run, elicit } = createTool({
      elicit: vi
        .fn()
        .mockRejectedValue(new McpError(ErrorCode.RequestTimeout, 'Request timed out')),
    });

    const result = await tool.createEvent(
      INPUT,
      { elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(run).not.toHaveBeenCalled();
    expect(result.success).toBe(false);
    expect(result.message).toMatch(/timed out/i);
    // The idempotency key comes back so a retry cannot double-book.
    expect(result.transactionId).toBe(INPUT.transactionId);
  });

  it('reuses the returned transactionId on retry so Graph can dedupe', async () => {
    const first = createTool({
      elicit: vi
        .fn()
        .mockRejectedValue(new McpError(ErrorCode.RequestTimeout, 'Request timed out')),
    });
    const { transactionId: generated, ...withoutId } = INPUT;
    const timedOut = await first.tool.createEvent(
      withoutId,
      { elicit: first.elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(timedOut.success).toBe(false);
    expect(timedOut.transactionId).toEqual(expect.stringMatching(/^[0-9a-f]{32}$/));
    expect(timedOut.transactionId).not.toBe(generated);

    const retryRun = vi.fn().mockResolvedValue({
      success: true,
      message: 'Created the event and sent invitations immediately.',
      transactionId: timedOut.transactionId,
    });
    const retry = createTool({ run: retryRun });
    await retry.tool.createEvent(
      { ...withoutId, transactionId: timedOut.transactionId },
      { elicit: retry.elicit } as unknown as Context,
      { user: { userProfileId: USER_PROFILE_ID.toString() } } as unknown as McpAuthenticatedRequest,
    );

    expect(retryRun).toHaveBeenCalledWith(
      USER_PROFILE_ID,
      expect.objectContaining({ transactionId: timedOut.transactionId }),
    );
  });
});
