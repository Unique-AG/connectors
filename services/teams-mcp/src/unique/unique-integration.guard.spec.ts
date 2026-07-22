import { describe, expect, it } from 'vitest';
import type { UniqueConfig } from '~/config';
import {
  assertRootScopeId,
  assertUniqueIntegrationEnabled,
  isUniqueIntegrationEnabled,
  UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE,
} from './unique-integration.guard';

const disabledConfig = { integration: 'disabled' } as UniqueConfig;

const enabledConfig = {
  integration: 'enabled',
  serviceAuthMode: 'external',
  apiBaseUrl: new URL('https://api.example.com/public/'),
  apiVersion: '2023-12-06',
  rootScopeId: 'scope_root_01',
  userFetchConcurrency: 5,
  serviceExtraHeaders: {
    authorization: 'Bearer app-key',
    'x-app-id': 'app_01',
    'x-user-id': 'user_01',
    'x-company-id': 'company_01',
  },
} as UniqueConfig;

describe('unique-integration.guard', () => {
  it('isUniqueIntegrationEnabled returns false when disabled', () => {
    expect(isUniqueIntegrationEnabled(disabledConfig)).toBe(false);
  });

  it('isUniqueIntegrationEnabled returns true when enabled', () => {
    expect(isUniqueIntegrationEnabled(enabledConfig)).toBe(true);
  });

  it('assertUniqueIntegrationEnabled throws a misconfiguration message when disabled', () => {
    expect(() => assertUniqueIntegrationEnabled(disabledConfig)).toThrow(
      UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE,
    );
  });

  it('assertUniqueIntegrationEnabled narrows to enabled config', () => {
    assertUniqueIntegrationEnabled(enabledConfig);
    expect(enabledConfig.rootScopeId).toBe('scope_root_01');
  });

  it('assertRootScopeId returns the root scope id', () => {
    assertUniqueIntegrationEnabled(enabledConfig);
    expect(assertRootScopeId(enabledConfig)).toBe('scope_root_01');
  });
});
