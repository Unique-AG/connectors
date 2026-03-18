import { type Scope, UniqueApiClient } from '@unique-ag/unique-api';
import { Logger } from '@nestjs/common';
import type { IngestionConfig } from '../config/ingestion.schema';

export class TenantCleanupService {
  private readonly logger = new Logger(TenantCleanupService.name);

  public constructor(
    private readonly tenantName: string,
    private readonly ingestionConfig: IngestionConfig,
    private readonly uniqueClient: UniqueApiClient,
  ) {}

  public async cleanup(): Promise<void> {
    const { scopeId, useV1KeyFormat } = this.ingestionConfig;

    const rootScope = await this.uniqueClient.scopes.getById(scopeId);
    if (!rootScope) {
      this.logger.log({
        tenantName: this.tenantName,
        msg: `Root scope ${scopeId} not found, skipping`,
      });
      return;
    }

    const childScopes = await this.uniqueClient.scopes.listChildren(scopeId);

    // For V1 tenants, content is owned by child scopes (flat hierarchy), so no child scopes = no content.
    // For V2 tenants, content is keyed by tenant name prefix, so we check the count directly.
    let hasContent = childScopes.length > 0;
    if (!useV1KeyFormat && !hasContent) {
      const contentCount = await this.uniqueClient.files.getCountByKeyPrefix(this.tenantName);
      hasContent = contentCount > 0;
    }

    if (childScopes.length === 0 && !hasContent) {
      this.logger.log({ tenantName: this.tenantName, msg: 'Already cleaned up, skipping' });
      return;
    }

    if (useV1KeyFormat) {
      await this.deleteContentByScopes(childScopes);
    } else {
      const deletedCount = await this.uniqueClient.files.deleteByKeyPrefix(this.tenantName);
      this.logger.log({
        tenantName: this.tenantName,
        deletedCount,
        msg: 'Content deleted by key prefix',
      });
    }

    let hasFailedScopes = false;
    for (const child of childScopes) {
      const result = await this.uniqueClient.scopes.delete(child.id, { recursive: true });
      if (result.failedFolders.length > 0) {
        hasFailedScopes = true;
        this.logger.warn({
          tenantName: this.tenantName,
          scopeName: child.name,
          succeeded: result.successFolders.length,
          failedFolders: result.failedFolders,
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
    }

    if (hasFailedScopes) {
      this.logger.warn({
        tenantName: this.tenantName,
        msg: 'Tenant cleanup completed with scope deletion failures',
      });
    } else {
      this.logger.log({ tenantName: this.tenantName, msg: 'Tenant cleanup completed' });
    }
  }

  private async deleteContentByScopes(scopes: Scope[]): Promise<void> {
    for (const scope of scopes) {
      const contentIds = await this.uniqueClient.files.getContentIdsByScope(scope.id);
      if (contentIds.length > 0) {
        await this.uniqueClient.files.deleteByIds(contentIds);
        this.logger.log({
          tenantName: this.tenantName,
          scopeName: scope.name,
          deletedCount: contentIds.length,
          msg: 'Content deleted by scope ownership',
        });
      }
    }
  }
}
