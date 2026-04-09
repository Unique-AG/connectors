import assert from 'node:assert';
import type { UniqueApiClient } from '@unique-ag/unique-api';
import { Logger } from '@nestjs/common';
import type { IngestionConfig } from '../config/ingestion.schema';
import type {
  ConfluenceApiClient,
  InstanceIdentifier,
} from '../confluence-api/confluence-api-client';
import {
  buildRootScopeExternalId,
  buildSpaceScopeExternalId,
} from '../constants/ingestion.constants';

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

  private async getInstanceIdentifier(): Promise<InstanceIdentifier> {
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
    assert.ok(userId, 'User ID must be available');

    // Grant access to root scope before reading it (service account needs permission to query scopes)
    await this.uniqueApiClient.scopes.createAccesses(this.ingestionConfig.scopeId, [
      { type: 'MANAGE', entityId: userId, entityType: 'USER' },
      { type: 'READ', entityId: userId, entityType: 'USER' },
      { type: 'WRITE', entityId: userId, entityType: 'USER' },
    ]);

    const rootScope = await this.uniqueApiClient.scopes.getById(this.ingestionConfig.scopeId);
    assert.ok(rootScope, `Root scope with ID ${this.ingestionConfig.scopeId} not found`);

    const isInitialSync = await this.validateOwnership(rootScope);

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

  private async validateOwnership(rootScope: {
    id: string;
    externalId: string | null;
  }): Promise<boolean> {
    const instanceId = await this.getInstanceIdentifier();
    const expectedExternalId = buildRootScopeExternalId(instanceId.type, instanceId.id);

    if (!rootScope.externalId) {
      // Claim fails fatally: if updateExternalId rejects (e.g. the Unique API enforces
      // cross-org uniqueness on externalId), the sync must not proceed. This prevents the
      // same Confluence instance from being ingested into two different Unique orgs.
      try {
        const updatedScope = await this.uniqueApiClient.scopes.updateExternalId(
          rootScope.id,
          expectedExternalId,
        );
        rootScope.externalId = updatedScope.externalId;
        this.logger.log({
          scopeId: rootScope.id,
          externalId: expectedExternalId,
          msg: 'Claimed root scope ownership',
        });
      } catch (error) {
        this.logger.error({
          scopeId: rootScope.id,
          externalId: expectedExternalId,
          err: error,
          msg: 'Failed to claim root scope ownership',
        });
        throw error;
      }
      return true;
    }

    assert.ok(
      rootScope.externalId === expectedExternalId,
      `Root scope ownership mismatch: expected ${expectedExternalId}, found ${rootScope.externalId}`,
    );
    return false;
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
        const externalId = buildSpaceScopeExternalId(this.tenantName, spaceKey);
        await this.uniqueApiClient.scopes.updateExternalId(scope.id, externalId);
      }

      result.set(spaceKey, scope.id);
    }

    this.logger.debug({ spaceKeys, count: spaceKeys.length, msg: 'Space scopes resolved' });
    return result;
  }
}
