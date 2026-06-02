/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { UnauthorizedException } from '@nestjs/common';
import { typeid } from 'typeid-js';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IngestMeetingTool } from './ingest-meeting.tool';

const USER_PROFILE_ID = typeid('user_profile').toString();
const MEETING_ID = 'meeting-123';
const JOIN_URL =
  'https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=%7b%7d';

const meetingRaw = {
  id: MEETING_ID,
  subject: 'Weekly Sync',
  startDateTime: '2024-01-15T10:00:00Z',
  endDateTime: '2024-01-15T11:00:00Z',
  joinWebUrl: JOIN_URL,
  participants: {
    attendees: [
      {
        upn: 'attendee@example.com',
        identity: { user: { id: 'att-1', tenantId: 'tenant-1', displayName: 'Att One' } },
      },
    ],
    organizer: {
      upn: 'organizer@example.com',
      identity: { user: { id: 'org-1', tenantId: 'tenant-1', displayName: 'Organizer' } },
    },
  },
};

const transcriptRaw = (id: string, createdDateTime: string) => ({
  id,
  meetingId: MEETING_ID,
  callId: 'call-1',
  contentCorrelationId: `corr-${id}`,
  transcriptContentUrl: `https://graph.microsoft.com/v1.0/me/onlineMeetings/${MEETING_ID}/transcripts/${id}/content`,
  createdDateTime,
  endDateTime: createdDateTime,
  meetingOrganizer: {
    application: null,
    device: null,
    user: {
      userIdentityType: 'aadUser',
      tenantId: 'tenant-1',
      id: 'org-1',
      displayName: 'Organizer',
    },
  },
});

/**
 * Build a Graph client mock whose `.api(path).filter(...).get()` and `.api(path).get()` resolve to
 * the configured collections based on the requested path.
 */
function makeClient(meetingValue: unknown[], transcriptValue: unknown[]) {
  const apiCalls: string[] = [];
  const client = {
    api: vi.fn((path: string) => {
      apiCalls.push(path);
      const builder: any = {
        filter: vi.fn(() => builder),
        get: vi.fn(async () => {
          if (path === '/me/onlineMeetings') {
            return { value: meetingValue };
          }
          if (path.endsWith('/transcripts')) {
            return { value: transcriptValue };
          }
          throw new Error(`unexpected path ${path}`);
        }),
      };
      return builder;
    }),
  };
  return { client, apiCalls };
}

function setup(meetingValue: unknown[], transcriptValue: unknown[]) {
  const { client, apiCalls } = makeClient(meetingValue, transcriptValue);
  const graphClientFactory = { createClientForUser: vi.fn(() => client) } as any;
  const transcriptCreated = { enqueueIngestRequested: vi.fn(async () => {}) } as any;
  const traceService = { getSpan: vi.fn(() => undefined) } as any;

  const elicitInput = vi.fn();
  const getClientCapabilities = vi.fn(() => ({ elicitation: {} }));
  const context = {
    mcpServer: { server: { getClientCapabilities, elicitInput } },
  } as any;
  const request = { user: { userProfileId: USER_PROFILE_ID } } as any;

  const tool = new IngestMeetingTool(traceService, graphClientFactory, transcriptCreated);

  return {
    tool,
    context,
    request,
    transcriptCreated,
    graphClientFactory,
    elicitInput,
    getClientCapabilities,
    apiCalls,
  };
}

describe('IngestMeetingTool', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('throws when the request is not authenticated', async () => {
    const { tool, context } = setup([meetingRaw], [transcriptRaw('t1', '2024-01-15T10:30:00Z')]);
    await expect(
      tool.ingestMeeting({ joinUrl: JOIN_URL }, context, { user: undefined } as any),
    ).rejects.toThrow(UnauthorizedException);
  });

  it('queues the single transcript when no date is given', async () => {
    const { tool, context, request, transcriptCreated, apiCalls } = setup(
      [meetingRaw],
      [transcriptRaw('t1', '2024-01-15T10:30:00Z')],
    );

    const result = await tool.ingestMeeting({ joinUrl: JOIN_URL }, context, request);

    expect(result.success).toBe(true);
    expect(result.meeting).toEqual({
      id: MEETING_ID,
      subject: 'Weekly Sync',
      joinUrl: expect.stringContaining('meetup-join'),
    });
    expect(result.queued).toHaveLength(1);
    expect(result.queued[0]).toMatchObject({ transcriptId: 't1' });
    expect(transcriptCreated.enqueueIngestRequested).toHaveBeenCalledTimes(1);
    expect(transcriptCreated.enqueueIngestRequested).toHaveBeenCalledWith(
      expect.objectContaining({ meetingId: MEETING_ID, transcriptId: 't1' }),
    );
    // Uses /me routes for the delegated on-demand path
    expect(apiCalls).toContain('/me/onlineMeetings');
    expect(apiCalls).toContain(`/me/onlineMeetings/${MEETING_ID}/transcripts`);
  });

  it('returns not-found when the join URL matches no meeting', async () => {
    const { tool, context, request, transcriptCreated } = setup([], []);

    const result = await tool.ingestMeeting({ joinUrl: JOIN_URL }, context, request);

    expect(result.success).toBe(false);
    expect(result.meeting).toBeNull();
    expect(result.queued).toEqual([]);
    expect(transcriptCreated.enqueueIngestRequested).not.toHaveBeenCalled();
  });

  it('returns failure when the meeting has no transcripts', async () => {
    const { tool, context, request, transcriptCreated } = setup([meetingRaw], []);

    const result = await tool.ingestMeeting({ joinUrl: JOIN_URL }, context, request);

    expect(result.success).toBe(false);
    expect(result.meeting).not.toBeNull();
    expect(result.queued).toEqual([]);
    expect(transcriptCreated.enqueueIngestRequested).not.toHaveBeenCalled();
  });

  it('selects the transcript matching the provided date without eliciting', async () => {
    const { tool, context, request, transcriptCreated, elicitInput } = setup(
      [meetingRaw],
      [transcriptRaw('t1', '2024-01-15T10:30:00Z'), transcriptRaw('t2', '2024-01-22T10:30:00Z')],
    );

    const result = await tool.ingestMeeting(
      { joinUrl: JOIN_URL, date: '2024-01-22' },
      context,
      request,
    );

    expect(result.success).toBe(true);
    expect(result.queued).toHaveLength(1);
    expect(result.queued[0]).toMatchObject({ transcriptId: 't2' });
    expect(elicitInput).not.toHaveBeenCalled();
    expect(transcriptCreated.enqueueIngestRequested).toHaveBeenCalledWith(
      expect.objectContaining({ transcriptId: 't2' }),
    );
  });

  it('returns the available dates when the provided date matches nothing', async () => {
    const { tool, context, request, transcriptCreated } = setup(
      [meetingRaw],
      [transcriptRaw('t1', '2024-01-15T10:30:00Z'), transcriptRaw('t2', '2024-01-22T10:30:00Z')],
    );

    const result = await tool.ingestMeeting(
      { joinUrl: JOIN_URL, date: '2024-02-01' },
      context,
      request,
    );

    expect(result.success).toBe(false);
    expect(result.message).toContain('2024-01-15');
    expect(result.message).toContain('2024-01-22');
    expect(transcriptCreated.enqueueIngestRequested).not.toHaveBeenCalled();
  });

  it('elicits a choice when multiple transcripts are ambiguous and queues the accepted one', async () => {
    const { tool, context, request, transcriptCreated, elicitInput } = setup(
      [meetingRaw],
      [transcriptRaw('t1', '2024-01-15T10:30:00Z'), transcriptRaw('t2', '2024-01-22T10:30:00Z')],
    );
    elicitInput.mockResolvedValue({ action: 'accept', content: { transcript: 't2' } });

    const result = await tool.ingestMeeting({ joinUrl: JOIN_URL }, context, request);

    expect(elicitInput).toHaveBeenCalledTimes(1);
    expect(result.success).toBe(true);
    expect(result.queued).toHaveLength(1);
    expect(result.queued[0]).toMatchObject({ transcriptId: 't2' });
    expect(transcriptCreated.enqueueIngestRequested).toHaveBeenCalledWith(
      expect.objectContaining({ transcriptId: 't2' }),
    );
  });

  it('returns cancelled when the user declines the elicitation', async () => {
    const { tool, context, request, transcriptCreated, elicitInput } = setup(
      [meetingRaw],
      [transcriptRaw('t1', '2024-01-15T10:30:00Z'), transcriptRaw('t2', '2024-01-22T10:30:00Z')],
    );
    elicitInput.mockResolvedValue({ action: 'cancel' });

    const result = await tool.ingestMeeting({ joinUrl: JOIN_URL }, context, request);

    expect(result.success).toBe(false);
    expect(result.message).toContain('cancelled');
    expect(transcriptCreated.enqueueIngestRequested).not.toHaveBeenCalled();
  });

  it('fails with guidance when the client cannot elicit and the choice is ambiguous', async () => {
    const { tool, context, request, transcriptCreated, getClientCapabilities, elicitInput } = setup(
      [meetingRaw],
      [transcriptRaw('t1', '2024-01-15T10:30:00Z'), transcriptRaw('t2', '2024-01-22T10:30:00Z')],
    );
    getClientCapabilities.mockReturnValue({} as any);

    const result = await tool.ingestMeeting({ joinUrl: JOIN_URL }, context, request);

    expect(result.success).toBe(false);
    expect(result.message).toContain('date');
    expect(elicitInput).not.toHaveBeenCalled();
    expect(transcriptCreated.enqueueIngestRequested).not.toHaveBeenCalled();
  });
});
