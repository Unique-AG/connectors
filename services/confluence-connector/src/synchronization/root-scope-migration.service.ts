import type { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared, smearPath } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';

export type MigrationResult =
  | { status: 'no_migration_needed' }
  | { status: 'migration_completed' }
  | { status: 'migration_failed'; error: string };

export class RootScopeMigrationService {
  private readonly logger = new Logger(RootScopeMigrationService.name);

  public constructor(private readonly uniqueApiClient: UniqueApiClient) {}

  public async migrateIfNeeded(
    newRootScopeId: string,
    expectedExternalId: string,
  ): Promise<MigrationResult> {
    try {
      const oldRoot = await this.uniqueApiClient.scopes.getByExternalId(expectedExternalId);

      if (!oldRoot) {
        this.logger.debug(
          `No previous root scope found for externalId ${expectedExternalId}, no migration needed`,
        );
        return { status: 'no_migration_needed' };
      }

      if (oldRoot.id === newRootScopeId) {
        this.logger.debug(`Old root scope ${oldRoot.id} is same as new root, no migration needed`);
        return { status: 'no_migration_needed' };
      }

      this.logger.log(
        `Found old root scope ${oldRoot.id} with externalId ${expectedExternalId}, migrating children to new root ${newRootScopeId}`,
      );

      const children = await this.uniqueApiClient.scopes.listChildren(oldRoot.id);
      this.logger.log(`Found ${children.length} children to migrate to new root ${newRootScopeId}`);

      let failedCount = 0;
      let firstError: string | undefined;

      for (const child of children) {
        try {
          await this.uniqueApiClient.scopes.updateParent(child.id, newRootScopeId);
        } catch (err) {
          failedCount++;
          if (firstError === undefined) {
            firstError = err instanceof Error ? err.message : String(err);
          }
        }
      }

      if (failedCount > 0) {
        return {
          status: 'migration_failed',
          error: `Failed to reparent ${failedCount} of ${children.length} children: ${firstError}`,
        };
      }

      this.logger.log(`Reparented ${children.length} children to new root ${newRootScopeId}`);

      const deleteResult = await this.uniqueApiClient.scopes.delete(oldRoot.id);

      if (deleteResult.failedFolders.length > 0) {
        this.logger.warn({
          msg: `Failed to delete old root scope ${oldRoot.id}`,
          failedFolders: deleteResult.failedFolders.map((f) => ({
            id: f.id,
            name: createSmeared(f.name),
            path: smearPath(createSmeared(f.path)),
            failReason: f.failReason,
          })),
        });
        return { status: 'migration_failed', error: 'Failed to delete old root scope' };
      }

      this.logger.log(`Migration completed successfully, old root ${oldRoot.id} deleted`);
      return { status: 'migration_completed' };
    } catch (error) {
      this.logger.error({
        msg: 'Root scope migration failed',
        err: error,
      });
      return {
        status: 'migration_failed',
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }
}
