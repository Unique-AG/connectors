import type pino from 'pino';
import type { IngestionConfig } from '../config/ingestion.schema';
import { CONFC_EXTERNAL_ID_PREFIX } from '../constants/ingestion.constants';
import type { UniqueApiClient } from '@unique-ag/unique-api';
import assert from 'assert';

export class ScopeManagementService {
  private rootScopePath: string | null = null;

  public constructor(
    private readonly ingestionConfig: IngestionConfig,
    private readonly tenantName: string,
    private readonly uniqueApiClient: UniqueApiClient,
    private readonly logger: pino.Logger,
  ) {}

  public async initialize(): Promise<void> {
    const userId = await this.uniqueApiClient.users.getCurrentId();

    // Grant access to root scope before reading it (service account needs permission to query scopes)
    await this.uniqueApiClient.scopes.createAccesses(this.ingestionConfig.scopeId, [
      { type: 'MANAGE', entityId: userId, entityType: 'USER' },
      { type: 'READ', entityId: userId, entityType: 'USER' },
      { type: 'WRITE', entityId: userId, entityType: 'USER' },
    ]);

    const rootScope = await this.uniqueApiClient.scopes.getById(this.ingestionConfig.scopeId);
    assert.ok(rootScope, `Root scope with ID ${this.ingestionConfig.scopeId} not found`);

    const pathSegments = [rootScope.name];
    let currentScope = rootScope;

    while (currentScope.parentId !== null) {
      // Grant READ access to parent scope before reading it
      await this.uniqueApiClient.scopes.createAccesses(currentScope.parentId, [
        { type: 'READ', entityId: userId, entityType: 'USER' },
      ]);

      const parentScope = await this.uniqueApiClient.scopes.getById(currentScope.parentId);
      assert.ok(parentScope, `Parent scope not found: ${currentScope.parentId}`);
      pathSegments.unshift(parentScope.name);
      currentScope = parentScope;
    }

    this.rootScopePath = `/${pathSegments.join('/')}`;
    this.logger.info({ rootScopePath: this.rootScopePath }, 'Scope management initialized');
  }

  public async ensureSpaceScopes(spaceKeys: string[]): Promise<Map<string, string>> {
    assert.ok(this.rootScopePath, 'ScopeManagementService not initialized — call initialize() first');

    const paths = spaceKeys.map((key) => `${this.rootScopePath}/${key}`);
    const createdScopes = await this.uniqueApiClient.scopes.createFromPaths(paths, {
      inheritAccess: true,
    });

    const result = new Map<string, string>();

    for (const [index, spaceKey] of spaceKeys.entries()) {
      const scope = createdScopes[index];
      assert.ok(scope, `Failed to create scope for space: ${spaceKey}`);

      if (!scope.externalId) {
        const externalId = `${CONFC_EXTERNAL_ID_PREFIX}${this.tenantName}:${spaceKey}`;
        await this.uniqueApiClient.scopes.updateExternalId(scope.id, externalId);
      }

      result.set(spaceKey, scope.id);
    }

    this.logger.debug({ spaceKeys, count: spaceKeys.length }, 'Space scopes resolved');
    return result;
  }
}
