import { describe, expect, it } from 'vitest';
import { UniqueAuthMode } from '../../../config';
import { ServiceRegistry } from '../../../tenant/service-registry';
import type { TenantContext } from '../../../tenant/tenant-context.interface';
import { tenantStorage } from '../../../tenant/tenant-context.storage';
import { Redacted } from '../../../utils/redacted';
import { ClusterLocalAuthStrategy } from '../strategies/cluster-local-auth.strategy';
import { ZitadelAuthStrategy } from '../strategies/zitadel-auth.strategy';
import { UniqueAuthFactory } from '../unique-auth.factory';

const baseFields = {
  ingestionServiceBaseUrl: 'https://ingestion.example.com',
  scopeManagementServiceBaseUrl: 'https://scope.example.com',
  apiRateLimitPerMinute: 100,
};

describe('UniqueAuthFactory', () => {
  const mockServiceRegistry = {
    getServiceLogger: () => ({ info: () => undefined }),
  } as unknown as ServiceRegistry;
  const factory = new UniqueAuthFactory(mockServiceRegistry);
  const mockTenant: TenantContext = {
    name: 'test-tenant',
    config: {} as TenantContext['config'],
    isScanning: false,
  };

  describe('create', () => {
    it('creates ClusterLocalAuthStrategy for cluster_local mode', () => {
      const config = {
        ...baseFields,
        serviceAuthMode: UniqueAuthMode.CLUSTER_LOCAL,
        serviceExtraHeaders: {
          'x-company-id': 'company-123',
          'x-user-id': 'user-456',
        },
      };

      const auth = tenantStorage.run(mockTenant, () => factory.create(config));

      expect(auth).toBeInstanceOf(ClusterLocalAuthStrategy);
    });

    it('creates ZitadelAuthStrategy for external mode', () => {
      const config = {
        ...baseFields,
        serviceAuthMode: UniqueAuthMode.EXTERNAL,
        zitadelOauthTokenUrl: 'https://zitadel.example.com/oauth/v2/token',
        zitadelProjectId: new Redacted('project-id'),
        zitadelClientId: 'client-id',
        zitadelClientSecret: new Redacted('client-secret'),
      };

      const auth = tenantStorage.run(mockTenant, () => factory.create(config));

      expect(auth).toBeInstanceOf(ZitadelAuthStrategy);
    });
  });
});
