import assert from 'node:assert';
import type { Scope, UniqueApiClient } from '@unique-ag/unique-api';
import { Logger } from '@nestjs/common';
import type { IngestionConfig } from '../config/ingestion.schema';
import {
  buildExternalId,
  buildPartialKey,
  type ParsedExternalId,
  parseExternalId,
} from '../utils/key-format';

export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);
  public constructor(
    private readonly ingestionConfig: IngestionConfig,
    private readonly tenantName: string,
    private readonly uniqueApiClient: UniqueApiClient,
  ) {}

  public async initialize(): Promise<string> {
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
    return rootScopePath;
  }

  public async ensureSpaceScopes(
    rootScopePath: string,
    spaceKeys: string[],
    spaceKeyToSpaceId: Map<string, string>,
  ): Promise<Map<string, string>> {
    const paths = spaceKeys.map((key) => `${rootScopePath}/${key}`);
    const createdScopes = await this.uniqueApiClient.scopes.createFromPaths(paths, {
      inheritAccess: true,
    });

    const result = new Map<string, string>();

    for (const [index, spaceKey] of spaceKeys.entries()) {
      const scope = createdScopes[index];
      assert.ok(scope, `Failed to create scope for space: ${spaceKey}`);

      const spaceId = spaceKeyToSpaceId.get(spaceKey);
      assert.ok(spaceId, `No spaceId found for spaceKey: ${spaceKey}`);

      const externalId = buildExternalId(this.tenantName, spaceId, spaceKey);
      if (scope.externalId !== externalId) {
        await this.uniqueApiClient.scopes.updateExternalId(scope.id, externalId);
      }

      result.set(spaceKey, scope.id);
    }

    this.logger.debug({ spaceKeys, count: spaceKeys.length, msg: 'Space scopes resolved' });
    return result;
  }

  public async cleanupRemovedSpaces(discoveredSpaceKeys: Set<string>): Promise<void> {
    if (discoveredSpaceKeys.size === 0) {
      this.logger.warn({
        msg: 'Skipping space cleanup because discovery returned zero spaces. This could indicate a Confluence API issue.',
      });
      return;
    }

    const children = await this.uniqueApiClient.scopes.listChildren(this.ingestionConfig.scopeId);

    const orphaned = this.identifyOrphanedScopes(children, discoveredSpaceKeys);

    if (orphaned.length === 0) {
      return;
    }

    this.logger.log({
      count: orphaned.length,
      msg: 'Cleaning up orphaned space scopes',
    });

    for (const { scope, parsed } of orphaned) {
      try {
        const partialKey = buildPartialKey(
          this.tenantName,
          parsed.spaceId,
          parsed.spaceKey,
          this.ingestionConfig.useV1KeyFormat,
        );

        const deletedFileCount = await this.uniqueApiClient.files.deleteByKeyPrefix(partialKey);
        await this.uniqueApiClient.scopes.delete(scope.id);

        this.logger.log({
          scopeId: scope.id,
          spaceKey: parsed.spaceKey,
          spaceId: parsed.spaceId,
          deletedFileCount,
          msg: 'Deleted orphaned space scope and its files',
        });
      } catch (error) {
        this.logger.error({
          scopeId: scope.id,
          spaceKey: parsed.spaceKey,
          err: error,
          msg: 'Failed to clean up orphaned space scope',
        });
      }
    }
  }

  private identifyOrphanedScopes(
    children: Scope[],
    discoveredSpaceKeys: Set<string>,
  ): Array<{ scope: Scope; parsed: ParsedExternalId }> {
    const result: Array<{ scope: Scope; parsed: ParsedExternalId }> = [];

    for (const child of children) {
      const parsed = parseExternalId(child.externalId ?? undefined);
      if (!parsed) {
        this.logger.warn({
          scopeId: child.id,
          scopeName: child.name,
          externalId: child.externalId,
          msg: 'Scope has missing or unparseable externalId, skipping cleanup',
        });
        continue;
      }
      if (!discoveredSpaceKeys.has(parsed.spaceKey)) {
        result.push({ scope: child, parsed });
      }
    }

    return result;
  }
}
