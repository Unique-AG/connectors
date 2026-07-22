import assert from 'node:assert';
import { type DynamicModule, Global, Module } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { EnabledUniqueConfig, UniqueConfigNamespaced } from '~/config';

export const KB_INTEGRATION_ENABLED_CONFIG = 'KB_INTEGRATION_ENABLED_CONFIG';

export const UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE =
  'Teams MCP is misconfigured: Unique integration is disabled or incomplete. Set UNIQUE_INTEGRATION=enabled and provide UNIQUE_ROOT_SCOPE_ID, UNIQUE_SERVICE_EXTRA_HEADERS, UNIQUE_API_BASE_URL, and related Unique configuration.';

/**
 * Sole fail-fast check for incomplete config: narrows the parsed union down to
 * EnabledUniqueConfig or throws. Downstream consumers inject the resulting
 * KB_INTEGRATION_ENABLED_CONFIG and never re-check it.
 */
export function createKbIntegrationEnabledConfig(
  config: ConfigService<UniqueConfigNamespaced, true>,
): EnabledUniqueConfig {
  const uniqueConfig = config.get('unique', { infer: true });
  assert.ok(uniqueConfig.integration === 'enabled', UNIQUE_INTEGRATION_MISCONFIGURED_MESSAGE);
  return uniqueConfig;
}

/**
 * Registered once via forRoot() from registerKbIntegrationModule(). Global so
 * any module in the graph can @Inject(KB_INTEGRATION_ENABLED_CONFIG) without
 * re-importing this module.
 */
@Global()
@Module({})
// biome-ignore lint/complexity/noStaticOnlyClass: Nest forRoot() module convention
export class KbIntegrationConfigModule {
  public static forRoot(): DynamicModule {
    return {
      module: KbIntegrationConfigModule,
      providers: [
        {
          provide: KB_INTEGRATION_ENABLED_CONFIG,
          inject: [ConfigService],
          useFactory: createKbIntegrationEnabledConfig,
        },
      ],
      exports: [KB_INTEGRATION_ENABLED_CONFIG],
    };
  }
}
