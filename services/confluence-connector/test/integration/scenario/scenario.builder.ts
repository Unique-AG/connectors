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
  // The configured root scope always exists in Unique (ScopeManagementService
  // expects it). List it first, unowned, so tests don't repeat the boilerplate;
  // a test that provides its own root scope (same id) overrides it, since
  // FakeUniqueApi seeds scopes by id with last-write-wins.
  const rootScope: ScenarioUniqueScope = {
    id: tenant.rootScopeId,
    name: tenant.rootScopeName,
    parentId: null,
    externalId: null,
  };
  return {
    tenant,
    confluence: {
      spaces: input.confluence?.spaces ?? DEFAULT_CONFLUENCE.spaces,
      pages: input.confluence?.pages ?? DEFAULT_CONFLUENCE.pages,
    },
    unique: {
      scopes: [rootScope, ...(input.unique?.scopes ?? DEFAULT_UNIQUE.scopes)],
      files: input.unique?.files ?? DEFAULT_UNIQUE.files,
      currentUserId: input.unique?.currentUserId ?? DEFAULT_UNIQUE.currentUserId,
    },
  };
}
