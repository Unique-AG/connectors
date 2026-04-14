import { type Scope, UniqueApiClient } from '@unique-ag/unique-api';
import { elapsedSeconds } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import type { Metrics } from '../metrics';
import { getCurrentTenant } from './tenant-context.storage';

export class TenantDeleteService {
  private readonly logger = new Logger(TenantDeleteService.name);

  public constructor(
    private readonly tenantName: string,
    private readonly scopeId: string,
    private readonly uniqueClient: UniqueApiClient,
    private readonly metrics: Metrics,
  ) {}

  public async deleteTenantContent(): Promise<void> {
    const tenant = getCurrentTenant();

    if (tenant.isScanning) {
      this.logger.log({
        tenantName: this.tenantName,
        msg: 'Cleanup already in progress, skipping',
      });
      return;
    }

    tenant.isScanning = true;
    const startTime = Date.now();

    try {
      const rootScope = await this.uniqueClient.scopes.getById(this.scopeId);
      if (!rootScope) {
        this.logger.log({
          tenantName: this.tenantName,
          msg: `Root scope ${this.scopeId} not found, skipping`,
        });
        return;
      }

      // Only child scopes are deleted. The root scope is intentionally preserved so the
      // tenant's top-level scope remains available for re-syncing without requiring
      // a new scope to be created on the Unique side.
      const childScopes = await this.uniqueClient.scopes.listChildren(this.scopeId);
      if (childScopes.length === 0) {
        this.logger.log({ tenantName: this.tenantName, msg: 'Already cleaned up, skipping' });
        return;
      }

      // Two-step deletion is intentional: deleteContentByScopes removes files in batches per
      // scope, then deleteChildScopes with recursive:true catches anything that failed in the
      // first step. This ensures no content is orphaned even if individual file deletions fail.
      await this.deleteContentByScopes(childScopes);
      await this.deleteChildScopes(childScopes);
      this.metrics.recordCleanupDuration(elapsedSeconds(startTime), 'success');
    } catch (error) {
      this.metrics.recordCleanupDuration(elapsedSeconds(startTime), 'failure');
      throw error;
    } finally {
      tenant.isScanning = false;
    }
  }

  private async deleteContentByScopes(scopes: Scope[]): Promise<void> {
    for (const scope of scopes) {
      try {
        const contentIds = await this.uniqueClient.files.getContentIdsByScope(scope.id);
        if (contentIds.length > 0) {
          await this.uniqueClient.files.deleteByIds(contentIds);
          this.metrics.recordCleanupContentDeleted(contentIds.length, 'success');
          this.logger.log({
            tenantName: this.tenantName,
            scopeName: scope.name,
            deletedCount: contentIds.length,
            msg: 'Content deleted by scope ownership',
          });
        }
      } catch (error) {
        this.metrics.recordCleanupContentDeleted(0, 'failure');
        this.logger.error({
          tenantName: this.tenantName,
          scopeName: scope.name,
          err: error,
          msg: 'Failed to delete content for scope',
        });
      }
    }
  }

  private async deleteChildScopes(childScopes: Scope[]): Promise<void> {
    for (const child of childScopes) {
      try {
        const result = await this.uniqueClient.scopes.delete(child.id, { recursive: true });
        if (result.failedFolders.length > 0) {
          this.metrics.recordCleanupScopesDeleted(result.successFolders.length, 'success');
          this.metrics.recordCleanupScopesDeleted(result.failedFolders.length, 'failure');
          this.logger.warn({
            tenantName: this.tenantName,
            scopeName: child.name,
            succeeded: result.successFolders.length,
            failed: result.failedFolders.length,
            msg: 'Partial scope deletion failure',
          });
        } else {
          this.metrics.recordCleanupScopesDeleted(result.successFolders.length, 'success');
          this.logger.log({
            tenantName: this.tenantName,
            scopeName: child.name,
            succeeded: result.successFolders.length,
            msg: 'Child scope deleted',
          });
        }
      } catch (error) {
        this.metrics.recordCleanupScopesDeleted(1, 'failure');
        this.logger.error({
          tenantName: this.tenantName,
          scopeName: child.name,
          err: error,
          msg: 'Failed to delete child scope',
        });
      }
    }
  }
}
