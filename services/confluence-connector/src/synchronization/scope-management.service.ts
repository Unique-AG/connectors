import assert from 'node:assert';
import type { UniqueApiClient } from '@unique-ag/unique-api';
import { Logger } from '@nestjs/common';
import type { ConfluenceApiClient, InstanceIdentifier } from '../confluence-api/confluence-api-client';
import type { IngestionConfig } from '../config/ingestion.schema';
import { EXTERNAL_ID_PREFIX, buildRootScopeExternalId } from '../constants/ingestion.constants';

export interface RootScopeInitResult {
  rootScopePath: string;
  isInitialSync: boolean;
}

export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);
  private cachedInstanceIdentifier: InstanceIdentifier | null = null;

  public constructor(
    private readonly ingestionConfig: IngestionConfig,
    private readonly tenantName: string,
    private readonly confluenceApiClient: ConfluenceApiClient,
    private readonly uniqueApiClient: UniqueApiClient,
  ) {}

  private async resolveAndCacheInstanceId(): Promise<InstanceIdentifier> {
    if (this.cachedInstanceIdentifier) {
      return this.cachedInstanceIdentifier;
    }
    const identifier = await this.confluenceApiClient.resolveInstanceIdentifier();
    this.cachedInstanceIdentifier = identifier;
    return identifier;
  }

  public async initialize(): Promise<RootScopeInitResult> {
    this.logger.log({
      tenantName: this.tenantName,
      msg: 'Requesting current user ID from Unique API',
    });
    const userId = await this.uniqueApiClient.users.getCurrentId();

    // Grant access to root scope before reading it (service account needs permission to query scopes)
    await this.uniqueApiClient.scopes.createAccesses(this.ingestionConfig.scopeId, [
      { type: 'MANAGE', entityId: userId, entityType: 'USER' },
      { type: 'READ', entityId: userId, entityType: 'USER' },
      { type: 'WRITE', entityId: userId, entityType: 'USER' },
    ]);

    const rootScope = await this.uniqueApiClient.scopes.getById(this.ingestionConfig.scopeId);
    assert.ok(rootScope, `Root scope with ID ${this.ingestionConfig.scopeId} not found`);

    const instanceId = await this.resolveAndCacheInstanceId();
    const expectedExternalId = buildRootScopeExternalId(instanceId.type, instanceId.id);
    let isInitialSync = false;

    if (rootScope.externalId === null) {
      isInitialSync = true;
      try {
        await this.uniqueApiClient.scopes.updateExternalId(rootScope.id, expectedExternalId);
        this.logger.log({
          scopeId: rootScope.id,
          externalId: expectedExternalId,
          msg: 'Claimed root scope ownership',
        });
      } catch (error) {
        this.logger.warn({
          scopeId: rootScope.id,
          externalId: expectedExternalId,
          error,
          msg: 'Failed to claim root scope ownership',
        });
      }
    } else {
      assert.ok(
        rootScope.externalId === expectedExternalId,
        `Root scope ownership mismatch: expected ${expectedExternalId}, found ${rootScope.externalId}`,
      );
    }

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

    const rootScopePath = `/${pathSegments.join('/')}`;
    this.logger.log({ rootScopePath, msg: 'Scope management initialized' });
    return { rootScopePath, isInitialSync };
  }

  public async ensureSpaceScopes(
    rootScopePath: string,
    spaceKeys: string[],
  ): Promise<Map<string, string>> {
    const paths = spaceKeys.map((key) => `${rootScopePath}/${key}`);
    const createdScopes = await this.uniqueApiClient.scopes.createFromPaths(paths, {
      inheritAccess: true,
    });

    const result = new Map<string, string>();

    for (const [index, spaceKey] of spaceKeys.entries()) {
      const scope = createdScopes[index];
      assert.ok(scope, `Failed to create scope for space: ${spaceKey}`);

      if (!scope.externalId) {
        const externalId = `${EXTERNAL_ID_PREFIX}${this.tenantName}:${spaceKey}`;
        await this.uniqueApiClient.scopes.updateExternalId(scope.id, externalId);
      }

      result.set(spaceKey, scope.id);
    }

    this.logger.debug({ spaceKeys, count: spaceKeys.length, msg: 'Space scopes resolved' });
    return result;
  }
}
