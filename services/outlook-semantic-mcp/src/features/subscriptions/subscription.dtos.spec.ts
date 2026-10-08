import { describe, expect, it } from 'vitest';
import { Subscription } from './subscription.dtos';

const baseSubscription = {
  id: 'subscription-1',
  resource: 'me/messages',
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
