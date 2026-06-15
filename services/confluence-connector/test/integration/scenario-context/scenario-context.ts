import type { SyncResult } from '../../../src/health/sync-result.types';
import type { Metrics } from '../../../src/metrics';
import { createNoopMetrics } from '../../../src/metrics/__mocks__/noop-metrics';
import { ConfluenceContentFetcher } from '../../../src/synchronization/confluence-content-fetcher';
import { ConfluencePageScanner } from '../../../src/synchronization/confluence-page-scanner';
import { ConfluenceSynchronizationService } from '../../../src/synchronization/confluence-synchronization.service';
import { FileDiffService } from '../../../src/synchronization/file-diff.service';
import { IngestionService } from '../../../src/synchronization/ingestion.service';
import { ScopeManagementService } from '../../../src/synchronization/scope-management.service';
import type { TenantContext } from '../../../src/tenant';
import { TenantDeleteService, tenantStorage } from '../../../src/tenant';
import type { DeleteResult } from '../../../src/tenant/tenant-delete-result.types';
import { FakeBlobStorage } from '../fakes/fake-blob-storage';
import { FakeConfluenceApi } from '../fakes/fake-confluence-api';
import { FakeUniqueApi } from '../fakes/fake-unique-api';
import { resolveTenantConfig } from '../scenario/resolve-tenant-config';
import type { Scenario } from '../scenario/scenario.types';

export interface ScenarioContext {
  readonly tenant: TenantContext;
  readonly confluence: FakeConfluenceApi;
  readonly unique: FakeUniqueApi;
  readonly metrics: Metrics;
  runSync(): Promise<SyncResult>;
  runDelete(): Promise<DeleteResult>;
}

/**
 * Wires the real synchronization stack around fakes for the two external boundaries.
 *
 * Mirrors `TenantRegistry.registerActiveTenantServices` 1:1, just substituting
 * ConfluenceApiClient and UniqueApiClient with stateful in-memory fakes.
 *
 * The pre-existing Unique scopes (including the root scope `defineScenario`
 * seeds by default) are loaded by `FakeUniqueApi` from `scenario.unique`, so
 * `synchronize()` can claim ownership and discover existing children naturally.
 */
export function buildScenarioContext(scenario: Scenario): ScenarioContext {
  const tenantConfig = resolveTenantConfig(scenario.tenant);
  const fakeConfluence = new FakeConfluenceApi(
    tenantConfig.confluence,
    tenantConfig.ingestion.attachments.enabled,
    scenario.confluence,
  );
  const fakeUnique = new FakeUniqueApi(scenario.unique);
  const blobStorage = new FakeBlobStorage(fakeUnique);
  const metrics = createNoopMetrics();

  const scanner = new ConfluencePageScanner(
    tenantConfig.confluence,
    tenantConfig.processing,
    fakeConfluence,
    tenantConfig.ingestion.attachments,
  );

  const contentFetcher = new ConfluenceContentFetcher(tenantConfig.confluence, fakeConfluence);

  const fileDiffService = new FileDiffService(
    tenantConfig.confluence,
    scenario.tenant.name,
    tenantConfig.ingestion.useV1KeyFormat,
    fakeUnique,
    metrics,
  );

  const ingestionService = new IngestionService(
    tenantConfig,
    scenario.tenant.name,
    fakeUnique,
    fakeConfluence,
    metrics,
    blobStorage.asDispatcher(),
  );

  const scopeManagementService = new ScopeManagementService(
    tenantConfig.ingestion,
    scenario.tenant.name,
    fakeConfluence,
    fakeUnique,
    metrics,
  );

  const syncService = new ConfluenceSynchronizationService(
    scanner,
    contentFetcher,
    fileDiffService,
    ingestionService,
    scopeManagementService,
    metrics,
  );

  const deleteService = new TenantDeleteService(
    scenario.tenant.name,
    tenantConfig.ingestion.scopeId,
    fakeUnique,
    metrics,
  );

  const tenant: TenantContext = {
    name: scenario.tenant.name,
    config: tenantConfig,
    status: 'active',
    isScanning: false,
  };

  return {
    tenant,
    confluence: fakeConfluence,
    unique: fakeUnique,
    metrics,
    runSync: () => tenantStorage.run(tenant, () => syncService.synchronize()),
    // The dedicated tenant-deletion flow the scheduler runs instead of runSync
    // when a tenant's status flips to deleted. It tears down every child scope
    // and its content while keeping the root scope. This is separate from the
    // per-content and per-space deletions that happen inside runSync.
    runDelete: () => tenantStorage.run(tenant, () => deleteService.deleteTenantContent()),
  };
}
