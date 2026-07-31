import type { ConfigService } from '@nestjs/config';
import { describe, expect, it, vi } from 'vitest';
import type { UniqueConfig, UniqueConfigNamespaced } from '~/config';
import {
  createKbIntegrationEnabledConfig,
  UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE,
} from './kb-integration-config.module';

const makeConfig = (unique: UniqueConfig) =>
  ({ get: vi.fn().mockReturnValue(unique) }) as unknown as ConfigService<
    UniqueConfigNamespaced,
    true
  >;

const disabledConfig = { integration: 'disabled' } as UniqueConfig;

const enabledConfig = {
  integration: 'enabled',
  serviceAuthMode: 'external',
  apiBaseUrl: new URL('https://api.example.com/public/'),
  apiVersion: '2023-12-06',
  rootScopeId: 'scope_root_01',
  userFetchConcurrency: 5,
  autoStartIngestion: false,
  serviceExtraHeaders: {
    authorization: 'Bearer app-key',
    'x-app-id': 'app_01',
    'x-user-id': 'user_01',
    'x-company-id': 'company_01',
  },
} as UniqueConfig;

describe('createKbIntegrationEnabledConfig', () => {
  it('throws a misconfiguration message when disabled', () => {
    expect(() => createKbIntegrationEnabledConfig(makeConfig(disabledConfig))).toThrow(
      UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE,
    );
  });

  it('returns the narrowed enabled config', () => {
    expect(createKbIntegrationEnabledConfig(makeConfig(enabledConfig))).toBe(enabledConfig);
  });
});
