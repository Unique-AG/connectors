import type pino from 'pino';
import type { IngestionConfig } from '../config/ingestion.schema';
import { CONFC_EXTERNAL_ID_PREFIX } from '../constants/ingestion.constants';
import type { UniqueApiClient } from '../unique-api';

export class ScopeManagementService {
  private rootScopePath: string | null = null;
  private readonly spaceScopes = new Map<string, string>();

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
    if (!rootScope) {
      throw new Error(`Root scope not found: ${this.ingestionConfig.scopeId}`);
    }

    const pathSegments: string[] = [rootScope.name];
    let currentScope = rootScope;

    while (currentScope.parentId !== null) {
      // Grant READ access to parent scope before reading it
      await this.uniqueApiClient.scopes.createAccesses(currentScope.parentId, [
        { type: 'READ', entityId: userId, entityType: 'USER' },
      ]);

      const parentScope = await this.uniqueApiClient.scopes.getById(currentScope.parentId);
      if (!parentScope) {
        throw new Error(`Parent scope not found: ${currentScope.parentId}`);
      }
      pathSegments.unshift(parentScope.name);
      currentScope = parentScope;
    }

    this.rootScopePath = `/${pathSegments.join('/')}`;
    this.logger.info({ rootScopePath: this.rootScopePath }, 'Scope management initialized');
  }

  public async ensureSpaceScope(spaceKey: string): Promise<string> {
    const cached = this.spaceScopes.get(spaceKey);
    if (cached) {
      return cached;
    }

    const externalId = `${CONFC_EXTERNAL_ID_PREFIX}${this.tenantName}:${spaceKey}`;

    const existingScope = await this.uniqueApiClient.scopes.getByExternalId(externalId);
    if (existingScope) {
      this.spaceScopes.set(spaceKey, existingScope.id);
      this.logger.debug({ spaceKey, scopeId: existingScope.id }, 'Found existing space scope');
      return existingScope.id;
    }

    if (!this.rootScopePath) {
      throw new Error('ScopeManagementService not initialized — call initialize() first');
    }

    const spaceScopePath = `${this.rootScopePath}/${spaceKey}`;
    const createdScopes = await this.uniqueApiClient.scopes.createFromPaths([spaceScopePath], {
      inheritAccess: true,
    });

    const createdScope = createdScopes[0];
    if (!createdScope) {
      throw new Error(`Failed to create scope for space: ${spaceKey}`);
    }

    await this.uniqueApiClient.scopes.updateExternalId(createdScope.id, externalId);

    this.spaceScopes.set(spaceKey, createdScope.id);
    this.logger.info(
      { spaceKey, scopeId: createdScope.id, externalId },
      'Created space scope',
    );

    return createdScope.id;
  }

  public async ensureSpaceScopes(spaceKeys: string[]): Promise<Map<string, string>> {
    if (!this.rootScopePath) {
      throw new Error('ScopeManagementService not initialized — call initialize() first');
    }

    const uniqueKeys = [...new Set(spaceKeys)];
    const result = new Map<string, string>();

    const uncachedKeys: string[] = [];
    for (const key of uniqueKeys) {
      const cached = this.spaceScopes.get(key);
      if (cached) {
        result.set(key, cached);
      } else {
        uncachedKeys.push(key);
      }
    }

    if (uncachedKeys.length === 0) {
      this.logger.info({ spaceKeys: uniqueKeys, count: uniqueKeys.length }, 'Batch space scopes resolved (all cached)');
      return result;
    }

    const paths = uncachedKeys.map((key) => `${this.rootScopePath}/${key}`);

    const createdScopes = await this.uniqueApiClient.scopes.createFromPaths(paths, {
      inheritAccess: true,
    });

    for (let i = 0; i < uncachedKeys.length; i++) {
      const spaceKey = uncachedKeys[i]!;
      const scope = createdScopes[i];
      if (!scope) {
        throw new Error(`Failed to create scope for space: ${spaceKey}`);
      }

      if (!scope.externalId) {
        const externalId = `${CONFC_EXTERNAL_ID_PREFIX}${this.tenantName}:${spaceKey}`;
        await this.uniqueApiClient.scopes.updateExternalId(scope.id, externalId);
      }

      this.spaceScopes.set(spaceKey, scope.id);
      result.set(spaceKey, scope.id);
    }

    this.logger.info({ spaceKeys: uniqueKeys, count: uniqueKeys.length }, 'Batch space scopes resolved');
    return result;
  }
}
