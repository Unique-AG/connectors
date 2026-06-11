import { AuthMode, type TenantConfig, UniqueAuthMode } from '../../../src/config';
import { Redacted } from '../../../src/utils/redacted';
import type { ScenarioTenantConfig } from './scenario.types';

const FAKE_INGESTION_BASE_URL = 'https://unique-fake.local/ingestion';
const FAKE_SCOPE_MANAGEMENT_BASE_URL = 'https://unique-fake.local/scope-management';

/**
 * Build a fully-typed TenantConfig from the simplified ScenarioTenantConfig.
 *
 * The unique config uses `external` auth mode so IngestionService.correctWriteUrl
 * passes through the writeUrl unchanged — the FakeBlobStorage MockAgent then
 * intercepts the PUT against that writeUrl host.
 */
export function resolveTenantConfig(scenario: ScenarioTenantConfig): TenantConfig {
  return {
    confluence: resolveConfluenceConfig(scenario),
    unique: {
      serviceAuthMode: UniqueAuthMode.External,
      zitadelOauthTokenUrl: 'https://zitadel.fake/oauth/token',
      zitadelClientId: 'fake-client-id',
      zitadelClientSecret: new Redacted('fake-client-secret'),
      zitadelProjectId: new Redacted('fake-project-id'),
      ingestionServiceBaseUrl: FAKE_INGESTION_BASE_URL,
      scopeManagementServiceBaseUrl: FAKE_SCOPE_MANAGEMENT_BASE_URL,
      apiRateLimitPerMinute: 1000,
    },
    processing: {
      concurrency: scenario.concurrency,
      scanIntervalCron: '*/15 * * * *',
      maxItemsToScan: scenario.maxItemsToScan,
    },
    ingestion: {
      ingestionMode: 'flat',
      scopeId: scenario.rootScopeId,
      storeInternally: scenario.storeInternally,
      useV1KeyFormat: scenario.useV1KeyFormat,
      attachments: {
        enabled: scenario.attachmentsEnabled,
        imageOcrEnabled: scenario.imageOcrEnabled,
        allowedMimeTypes: scenario.allowedMimeTypes.map((t) => t.toLowerCase()),
        maxFileSizeMb: scenario.maxFileSizeMb,
      },
    },
  };
}

function resolveConfluenceConfig(scenario: ScenarioTenantConfig): TenantConfig['confluence'] {
  const base = {
    baseUrl: scenario.instance.baseUrl,
    apiRateLimitPerMinute: 1000,
    ingestSingleLabel: scenario.ingestSingleLabel,
    ingestAllLabel: scenario.ingestAllLabel,
    auth: {
      mode: AuthMode.OAuth2Lo,
      clientId: 'fake-client-id',
      clientSecret: new Redacted('fake-client-secret'),
    },
  } as const;

  if (scenario.instance.type === 'cloud') {
    return {
      ...base,
      instanceType: 'cloud',
      cloudId: scenario.instance.cloudId,
    };
  }

  return {
    ...base,
    instanceType: 'data-center',
  };
}
