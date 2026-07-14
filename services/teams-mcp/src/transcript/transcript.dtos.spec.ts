import { describe, expect, it } from 'vitest';
import { Transcript } from './transcript.dtos';

const baseTranscript = {
  id: 'transcript-1',
  meetingId: 'meeting-1',
  callId: 'call-1',
  contentCorrelationId: 'correlation-1',
  transcriptContentUrl: 'https://graph.microsoft.com/v1.0/transcript/content',
  createdDateTime: '2026-07-14T10:00:00Z',
  endDateTime: '2026-07-14T11:00:00Z',
  meetingOrganizer: {
    application: null,
    device: null,
    user: {
      userIdentityType: 'aadUser',
      tenantId: 'tenant-1',
      id: 'user-1',
      displayName: 'Organizer',
    },
  },
};

describe('Transcript', () => {
  it('parses a fully populated transcript', () => {
    const result = Transcript.parse(baseTranscript);
    expect(result.contentCorrelationId).toBe('correlation-1');
    expect(result.meetingOrganizer.user.tenantId).toBe('tenant-1');
  });

  it('accepts a null contentCorrelationId when the transcript has no recording', () => {
    const result = Transcript.parse({ ...baseTranscript, contentCorrelationId: null });
    expect(result.contentCorrelationId).toBeNull();
  });

  it('accepts a missing tenantId on the meeting organizer', () => {
    const { tenantId: _tenantId, ...userWithoutTenant } = baseTranscript.meetingOrganizer.user;
    const result = Transcript.parse({
      ...baseTranscript,
      meetingOrganizer: {
        ...baseTranscript.meetingOrganizer,
        user: userWithoutTenant,
      },
    });
    expect(result.meetingOrganizer.user.tenantId).toBeUndefined();
  });

  it('still requires the transcript id', () => {
    const { id: _id, ...withoutId } = baseTranscript;
    expect(() => Transcript.parse(withoutId)).toThrow();
  });
});
