import type {
  Scenario,
  ScenarioConfluence,
  ScenarioTenantConfig,
  ScenarioUnique,
  ScenarioUniqueScope,
} from './scenario.types';

export interface ScenarioInput {
  tenant?: Partial<ScenarioTenantConfig>;
  confluence?: Partial<ScenarioConfluence>;
  unique?: Partial<ScenarioUnique>;
}

const DEFAULT_TENANT: ScenarioTenantConfig = {
  name: 'tenant1',
  instance: { type: 'cloud', cloudId: 'cloud-1', baseUrl: 'https://tenant1.atlassian.net' },
  ingestSingleLabel: 'ai-ingest',
  ingestAllLabel: 'ai-ingest-all',
  rootScopeId: 'root-scope-id',
  rootScopeName: 'Confluence',
  useV1KeyFormat: false,
  storeInternally: true,
  imageOcrEnabled: false,
  attachmentsEnabled: true,
  allowedMimeTypes: ['application/pdf', 'image/jpeg', 'image/png', 'text/plain'],
  maxFileSizeMb: 50,
  concurrency: 4,
  maxItemsToScan: undefined,
};

const DEFAULT_CONFLUENCE: ScenarioConfluence = {
  spaces: [],
  pages: [],
};

const DEFAULT_UNIQUE: ScenarioUnique = {
  scopes: [],
  files: [],
  currentUserId: 'test-user-id',
};

export function defineScenario(input: ScenarioInput = {}): Scenario {
  const tenant: ScenarioTenantConfig = { ...DEFAULT_TENANT, ...input.tenant };
  return {
    tenant,
    confluence: {
      spaces: input.confluence?.spaces ?? DEFAULT_CONFLUENCE.spaces,
      pages: input.confluence?.pages ?? DEFAULT_CONFLUENCE.pages,
    },
    unique: {
      scopes: ensureRootScope(input.unique?.scopes ?? DEFAULT_UNIQUE.scopes, tenant),
      files: input.unique?.files ?? DEFAULT_UNIQUE.files,
      currentUserId: input.unique?.currentUserId ?? DEFAULT_UNIQUE.currentUserId,
    },
  };
}

/**
 * `ScopeManagementService.initialize()` expects the configured root scope to
 * already exist in Unique. Seed it by default (unowned: `externalId === null`)
 * so individual tests don't have to repeat that boilerplate. Tests that care
 * about the root scope's state (e.g. ownership or migration) provide their own
 * scope with the same id, in which case theirs wins untouched.
 */
function ensureRootScope(
  scopes: ScenarioUniqueScope[],
  tenant: ScenarioTenantConfig,
): ScenarioUniqueScope[] {
  const hasRoot = scopes.some((scope) => scope.id === tenant.rootScopeId);
  if (hasRoot) {
    return scopes;
  }
  return [
    { id: tenant.rootScopeId, name: tenant.rootScopeName, parentId: null, externalId: null },
    ...scopes,
  ];
}
