import { describe, expect, it } from 'vitest';
import { Redacted } from '../../utils/redacted';
import { ClusterLocalAuthStrategy } from './strategies/cluster-local-auth.strategy';
import { ZitadelAuthStrategy } from './strategies/zitadel-auth.strategy';
import { UniqueAuthFactory } from './unique-auth.factory';

const baseFields = {
  ingestionServiceBaseUrl: 'https://ingestion.example.com',
  scopeManagementServiceBaseUrl: 'https://scope.example.com',
  apiRateLimitPerMinute: 100,
};

describe('UniqueAuthFactory', () => {
  const factory = new UniqueAuthFactory();

  describe('create', () => {
    it('creates ClusterLocalAuthStrategy for cluster_local mode', () => {
      const config = {
        ...baseFields,
        serviceAuthMode: 'cluster_local' as const,
        serviceExtraHeaders: {
          'x-company-id': 'company-123',
          'x-user-id': 'user-456',
        },
      };

      const auth = factory.create(config);

      expect(auth).toBeInstanceOf(ClusterLocalAuthStrategy);
    });

    it('creates ZitadelAuthStrategy for external mode', () => {
      const config = {
        ...baseFields,
        serviceAuthMode: 'external' as const,
        zitadelOauthTokenUrl: 'https://zitadel.example.com/oauth/v2/token',
        zitadelProjectId: new Redacted('project-id'),
        zitadelClientId: 'client-id',
        zitadelClientSecret: new Redacted('client-secret'),
      };

      const auth = factory.create(config);

      expect(auth).toBeInstanceOf(ZitadelAuthStrategy);
    });
  });
});
