import { type Scope, UniqueApiClient } from '@unique-ag/unique-api';
import { elapsedSeconds } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import type { Metrics } from '../metrics';
import { getCurrentTenant } from './tenant-context.storage';
import { type DeleteResult, DeleteSkipReason } from './tenant-delete-result.types';

export class TenantDeleteService {
  private readonly logger = new Logger(TenantDeleteService.name);

  public constructor(
    private readonly tenantName: string,
    private readonly scopeId: string,
    private readonly uniqueClient: UniqueApiClient,
    private readonly metrics: Metrics,
  ) {}

  public async deleteTenantContent(): Promise<DeleteResult> {
    const tenant = getCurrentTenant();

    if (tenant.isScanning) {
      this.logger.log({
        tenantName: this.tenantName,
        msg: 'Cleanup already in progress, skipping',
      });
      return { status: 'skipped', reason: DeleteSkipReason.ScanInProgress };
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
        return { status: 'skipped', reason: DeleteSkipReason.RootScopeNotFound };
      }

      // A null externalId is our "cleanup completed" marker: it is only cleared after a
      // fully successful deletion run, so its absence reliably signals there is no content
      // left to remove.
      if (rootScope.externalId === null) {
        this.logger.log({
          tenantName: this.tenantName,
          msg: 'Root scope externalId already cleared, skipping',
        });
        return { status: 'skipped', reason: DeleteSkipReason.AlreadyCleanedUp };
      }

      // Only child scopes are deleted. The root scope is intentionally preserved so the
      // tenant's top-level scope remains available for re-syncing without requiring
      // a new scope to be created on the Unique side.
      const childScopes = await this.uniqueClient.scopes.listChildren(this.scopeId);
      if (childScopes.length === 0) {
        this.logger.log({ tenantName: this.tenantName, msg: 'Already cleaned up, skipping' });
        return { status: 'skipped', reason: DeleteSkipReason.AlreadyCleanedUp };
      }

      // Two-step deletion is intentional: deleteContentByScopes removes files in batches per
      // scope, then deleteChildScopes with recursive:true catches anything that failed in the
      // first step. This ensures no content is orphaned even if individual file deletions fail.
      const contentFailures = await this.deleteContentByScopes(childScopes);
      const scopeFailures = await this.deleteChildScopes(childScopes);
      let totalFailures = contentFailures + scopeFailures;

      // Clearing the externalId signals that cleanup completed and frees the user to delete
      // the root scope if they want. Only attempted when deletion succeeded: a still-set
      // externalId on a partially-cleaned tenant is a useful "retry me" marker.
      if (totalFailures === 0 && rootScope.externalId !== null) {
        totalFailures += await this.clearRootExternalId();
      }

      const result: DeleteResult =
        totalFailures > 0 ? { status: 'failure', failures: totalFailures } : { status: 'success' };

      this.metrics.recordCleanupDuration(elapsedSeconds(startTime), result.status);
      return result;
    } catch (error) {
      this.metrics.recordCleanupDuration(elapsedSeconds(startTime), 'failure');
      throw error;
    } finally {
      tenant.isScanning = false;
    }
  }

  private async clearRootExternalId(): Promise<number> {
    try {
      await this.uniqueClient.scopes.updateExternalId(this.scopeId, null);
      this.logger.log({
        tenantName: this.tenantName,
        msg: 'Cleared root scope externalId',
      });
      return 0;
    } catch (error) {
      this.logger.error({
        tenantName: this.tenantName,
        err: error,
        msg: 'Failed to clear root scope externalId',
      });
      return 1;
    }
  }

  private async deleteContentByScopes(scopes: Scope[]): Promise<number> {
    let failures = 0;
    for (const scope of scopes) {
      try {
        const contentIds = await this.uniqueClient.files.getContentIdsByScope(scope.id);
        if (contentIds.length > 0) {
          const { deleted, failed } = await this.uniqueClient.files.deleteByIds(contentIds);
          if (deleted > 0) {
            this.metrics.recordCleanupContentDeleted(deleted, 'success');
          }
          if (failed > 0) {
            failures += failed;
            this.metrics.recordCleanupContentDeleted(failed, 'failure');
          }
          this.logger.log({
            tenantName: this.tenantName,
            scopeName: scope.name,
            deletedCount: deleted,
            failedCount: failed,
            msg: 'Content deleted by scope ownership',
          });
        }
      } catch (error) {
        failures++;
        this.logger.error({
          tenantName: this.tenantName,
          scopeName: scope.name,
          err: error,
          msg: 'Failed to delete content for scope',
        });
      }
    }
    return failures;
  }

  private async deleteChildScopes(childScopes: Scope[]): Promise<number> {
    let failures = 0;
    for (const child of childScopes) {
      try {
        const result = await this.uniqueClient.scopes.delete(child.id, { recursive: true });
        if (result.successFolders.length > 0) {
          this.metrics.recordCleanupScopesDeleted(result.successFolders.length, 'success');
        }
        if (result.failedFolders.length > 0) {
          failures += result.failedFolders.length;
          this.metrics.recordCleanupScopesDeleted(result.failedFolders.length, 'failure');
          this.logger.warn({
            tenantName: this.tenantName,
            scopeName: child.name,
            succeeded: result.successFolders.length,
            failed: result.failedFolders.length,
            msg: 'Partial scope deletion failure',
          });
        } else {
          this.logger.log({
            tenantName: this.tenantName,
            scopeName: child.name,
            succeeded: result.successFolders.length,
            msg: 'Child scope deleted',
          });
        }
      } catch (error) {
        failures++;
        this.metrics.recordCleanupScopesDeleted(1, 'failure');
        this.logger.error({
          tenantName: this.tenantName,
          scopeName: child.name,
          err: error,
          msg: 'Failed to delete child scope',
        });
      }
    }
    return failures;
  }
}
