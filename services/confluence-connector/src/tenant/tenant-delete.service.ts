import { type Scope, UniqueApiClient } from '@unique-ag/unique-api';
import { Logger } from '@nestjs/common';

export class TenantDeleteService {
  private readonly logger = new Logger(TenantDeleteService.name);

  public constructor(
    private readonly tenantName: string,
    private readonly scopeId: string,
    private readonly uniqueClient: UniqueApiClient,
  ) {}

  public async deleteTenantContent(): Promise<void> {
    const rootScope = await this.uniqueClient.scopes.getById(this.scopeId);
    if (!rootScope) {
      this.logger.log({
        tenantName: this.tenantName,
        msg: `Root scope ${this.scopeId} not found, skipping`,
      });
      return;
    }

    const childScopes = await this.uniqueClient.scopes.listChildren(this.scopeId);
    if (childScopes.length === 0) {
      this.logger.log({ tenantName: this.tenantName, msg: 'Already cleaned up, skipping' });
      return;
    }

    await this.deleteContentByScopes(childScopes);
    await this.deleteChildScopes(childScopes);
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

  private async deleteChildScopes(childScopes: Scope[]): Promise<void> {
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
}
