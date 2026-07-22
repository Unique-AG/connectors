import assert from 'node:assert';
import type { EnabledUniqueConfig, UniqueConfig } from '~/config';

export const UNIQUE_INTEGRATION_DISABLED_TOOL_MESSAGE =
  'Unique integration is disabled (UNIQUE_INTEGRATION=disabled). Enable it and configure Unique to use this tool.';

export const UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE =
  'Teams MCP is misconfigured: Unique integration is disabled or incomplete. Set UNIQUE_INTEGRATION=enabled and provide UNIQUE_ROOT_SCOPE_ID, UNIQUE_SERVICE_EXTRA_HEADERS, UNIQUE_API_BASE_URL, and related Unique configuration.';

export function isUniqueIntegrationEnabled(config: UniqueConfig): config is EnabledUniqueConfig {
  return config.integration === 'enabled';
}

export function assertUniqueIntegrationEnabled(
  config: UniqueConfig,
): asserts config is EnabledUniqueConfig {
  assert.ok(isUniqueIntegrationEnabled(config), UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE);
}

export function assertRootScopeId(config: EnabledUniqueConfig): string {
  assert.ok(
    config.rootScopeId,
    `${UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE} UNIQUE_ROOT_SCOPE_ID is required when Unique integration is enabled.`,
  );
  return config.rootScopeId;
}
