import { describe, expect, it } from 'vitest';
import { Subscription, Transcript } from './transcript.dtos';

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

const baseSubscription = {
  id: 'subscription-1',
  resource: 'communications/onlineMeetings/getAllTranscripts',
  applicationId: 'application-1',
  changeType: 'created',
  clientState: 'client-state-1',
  notificationUrl: 'https://example.com/webhooks/notifications',
  lifecycleNotificationUrl: 'https://example.com/webhooks/lifecycle',
  expirationDateTime: '2026-07-14T11:00:00Z',
  creatorId: 'creator-1',
  latestSupportedTlsVersion: 'v1_2',
  notificationUrlAppId: null,
  notificationQueryOptions: null,
  encryptionCertificate: null,
  encryptionCertificateId: null,
  includeResourceData: null,
};

describe('Subscription', () => {
  it('parses a fully populated subscription', () => {
    const result = Subscription.parse(baseSubscription);
    expect(result.id).toBe('subscription-1');
    expect(result.latestSupportedTlsVersion).toBe('v1_2');
  });

  it('accepts a null latestSupportedTlsVersion, which Graph deprecated', () => {
    const result = Subscription.parse({ ...baseSubscription, latestSupportedTlsVersion: null });
    expect(result.latestSupportedTlsVersion).toBeNull();
  });

  it('accepts a missing latestSupportedTlsVersion', () => {
    const { latestSupportedTlsVersion: _tlsVersion, ...withoutTlsVersion } = baseSubscription;
    const result = Subscription.parse(withoutTlsVersion);
    expect(result.latestSupportedTlsVersion).toBeUndefined();
  });

  it('still requires the subscription id', () => {
    const { id: _id, ...withoutId } = baseSubscription;
    expect(() => Subscription.parse(withoutId)).toThrow();
  });
});
