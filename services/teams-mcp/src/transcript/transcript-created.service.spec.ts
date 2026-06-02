/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { fromString, parseTypeId, typeid } from 'typeid-js';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TranscriptCreatedService } from './transcript-created.service';

const USER_ID = 'aad-user-1';
const MEETING_ID = 'meeting-123';
const TRANSCRIPT_ID = 't1';
const USER_PROFILE_ID = 'user_profile_01kt3wszt1fvp9p4bc6s8cc2vq';
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

const transcriptRaw = {
  id: TRANSCRIPT_ID,
  meetingId: MEETING_ID,
  callId: 'call-1',
  contentCorrelationId: 'corr-1',
  transcriptContentUrl: `https://graph.microsoft.com/v1.0/me/onlineMeetings/${MEETING_ID}/transcripts/${TRANSCRIPT_ID}/content`,
  createdDateTime: '2024-01-15T10:30:00Z',
  endDateTime: '2024-01-15T10:45:00Z',
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
};

/** Graph client mock that records the `.api()` paths and resolves meeting/transcript by suffix. */
function makeClient() {
  const apiCalls: string[] = [];
  const client = {
    api: vi.fn((path: string) => {
      apiCalls.push(path);
      const builder: any = {
        get: vi.fn(async () => {
          if (path.endsWith(`/onlineMeetings/${MEETING_ID}`)) {
            return meetingRaw;
          }
          if (path.endsWith(`/transcripts/${TRANSCRIPT_ID}`)) {
            return transcriptRaw;
          }
          throw new Error(`unexpected path ${path}`);
        }),
      };
      return builder;
    }),
  };
  return { client, apiCalls };
}

function setup() {
  const { client, apiCalls } = makeClient();
  const graphClientFactory = { createClientForUser: vi.fn(() => client) } as any;
  const unique = { ingestTranscript: vi.fn(async () => {}) } as any;
  const recordingService = { fetchRecording: vi.fn(async () => null) } as any;
  const amqp = { publish: vi.fn(async () => true) } as any;
  const trace = { getSpan: vi.fn(() => undefined) } as any;
  const db = {
    query: {
      subscriptions: {
        findFirst: vi.fn(async () => ({ userProfileId: USER_PROFILE_ID })),
      },
    },
  } as any;

  const service = new TranscriptCreatedService(
    amqp,
    trace,
    db,
    graphClientFactory,
    unique,
    recordingService,
  );

  return { service, unique, recordingService, graphClientFactory, apiCalls, db };
}

describe('TranscriptCreatedService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('created() ingests via /users/{userId} routes', async () => {
    const { service, unique, recordingService, apiCalls } = setup();
    const resource = `users('${USER_ID}')/onlineMeetings('${MEETING_ID}')/transcripts('${TRANSCRIPT_ID}')`;

    await service.created('sub-1', resource);

    expect(apiCalls).toContain(`/users/${USER_ID}/onlineMeetings/${MEETING_ID}`);
    expect(apiCalls).toContain(
      `/users/${USER_ID}/onlineMeetings/${MEETING_ID}/transcripts/${TRANSCRIPT_ID}`,
    );
    expect(recordingService.fetchRecording).toHaveBeenCalledWith(
      USER_PROFILE_ID,
      `/users/${USER_ID}`,
      MEETING_ID,
      'corr-1',
    );
    expect(unique.ingestTranscript).toHaveBeenCalledTimes(1);
  });

  it('ingestRequested() ingests via /me routes with identical downstream payload', async () => {
    const createdRun = setup();
    const resource = `users('${USER_ID}')/onlineMeetings('${MEETING_ID}')/transcripts('${TRANSCRIPT_ID}')`;
    await createdRun.service.created('sub-1', resource);
    // biome-ignore lint/style/noNonNullAssertion: ingestTranscript was awaited above
    const createdIngestArgs = createdRun.unique.ingestTranscript.mock.calls[0]!;

    const pid = parseTypeId(fromString(USER_PROFILE_ID, 'user_profile'));
    const requestedRun = setup();
    await requestedRun.service.ingestRequested({
      type: 'unique.teams-mcp.transcript.change-notification.ingest-requested',
      userProfileId: typeid(pid.prefix, pid.suffix),
      meetingId: MEETING_ID,
      transcriptId: TRANSCRIPT_ID,
    });

    // Uses /me routes
    expect(requestedRun.apiCalls).toContain(`/me/onlineMeetings/${MEETING_ID}`);
    expect(requestedRun.apiCalls).toContain(
      `/me/onlineMeetings/${MEETING_ID}/transcripts/${TRANSCRIPT_ID}`,
    );
    expect(requestedRun.recordingService.fetchRecording).toHaveBeenCalledWith(
      USER_PROFILE_ID,
      '/me',
      MEETING_ID,
      'corr-1',
    );

    // Identical ingest payload (meeting metadata + transcript id) regardless of route
    // biome-ignore lint/style/noNonNullAssertion: ingestTranscript was awaited above
    const requestedIngestArgs = requestedRun.unique.ingestTranscript.mock.calls[0]!;
    expect(requestedIngestArgs[0]).toEqual(createdIngestArgs[0]);
    expect(requestedIngestArgs[1].id).toEqual(createdIngestArgs[1].id);
  });

  it('enqueueIngestRequested() publishes the ingest-requested event', async () => {
    const { service } = setup();
    const amqpPublish = (service as any).amqp.publish as ReturnType<typeof vi.fn>;

    await service.enqueueIngestRequested({
      userProfileId: typeid('user_profile'),
      meetingId: MEETING_ID,
      transcriptId: TRANSCRIPT_ID,
    } as any);

    expect(amqpPublish).toHaveBeenCalledTimes(1);
    // biome-ignore lint/style/noNonNullAssertion: publish was awaited above
    const [, routingKey, payload] = amqpPublish.mock.calls[0]!;
    expect(routingKey).toBe('unique.teams-mcp.transcript.change-notification.ingest-requested');
    expect(payload).toMatchObject({
      type: 'unique.teams-mcp.transcript.change-notification.ingest-requested',
      meetingId: MEETING_ID,
      transcriptId: TRANSCRIPT_ID,
    });
    expect(typeof payload.userProfileId).toBe('string');
  });
});
