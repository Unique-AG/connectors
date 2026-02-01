import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { EXTERNAL_ID_PREFIX, shouldConcealLogs, smear, smearPath } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';

export type MigrationResult =
  | { status: 'no_migration_needed' }
  | { status: 'migration_completed' }
  | { status: 'migration_failed'; error: string };

@Injectable()
export class RootScopeMigrationService {
  private readonly logger = new Logger(RootScopeMigrationService.name);
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async migrateIfNeeded(newRootScopeId: string, siteId: string): Promise<MigrationResult> {
    const externalId = `${EXTERNAL_ID_PREFIX}site:${siteId}`;
    const logPrefix = `[Migration: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;

    try {
      const oldRoot = await this.uniqueScopesService.getScopeByExternalId(externalId);

      if (!oldRoot) {
        this.logger.debug(`${logPrefix} No previous root scope found`);
        return { status: 'no_migration_needed' };
      }

      // This case shouldn't ever happen, but we guard against it just in case
      if (oldRoot.id === newRootScopeId) {
        this.logger.debug(`${logPrefix} Old root is same as new root, no migration needed`);
        return { status: 'no_migration_needed' };
      }

      this.logger.log(
        `${logPrefix} Found old root scope ${oldRoot.id}, migrating children to new root ${newRootScopeId}`,
      );

      const children = await this.uniqueScopesService.listChildrenScopes(oldRoot.id);
      this.logger.log(`${logPrefix} Found ${children.length} children to migrate`);

      let failedCount = 0;
      for (const child of children) {
        try {
          await this.uniqueScopesService.updateScopeParent(child.id, newRootScopeId);
          this.logger.debug(`${logPrefix} Moved child scope ${child.id} to new root`);
        } catch (error) {
          this.logger.error({
            msg: `${logPrefix} Failed to move child scope ${child.id} to new root`,
            error: sanitizeError(error),
          });
          failedCount++;
        }
      }

      if (failedCount > 0) {
        return {
          status: 'migration_failed',
          error: `Failed to move ${failedCount}/${children.length} child scopes to new root`,
        };
      }

      this.logger.log(`${logPrefix} Deleting old root scope ${oldRoot.id}`);
      const result = await this.uniqueScopesService.deleteScopeRecursively(oldRoot.id);

      if (result.successFolders.length > 0) {
        if (result.successFolders.length > 1) {
          const deletedFolders = result.successFolders.map((f) =>
            this.shouldConcealLogs ? smear(f.name) : f.name,
          );
          this.logger.warn(
            `${logPrefix} Successfully deleted old root scope and ` +
              `${result.successFolders.length - 1} child folders: ${deletedFolders.join(', ')}`,
          );
        } else {
          this.logger.log(`${logPrefix} Successfully deleted old root scope`);
        }
      }

      if (result.failedFolders.length > 0) {
        this.logger.warn({
          msg: `${logPrefix} Failed to delete old root due to ${result.failedFolders.length} folders`,
          failedFolders: result.failedFolders.map((f) => ({
            id: f.id,
            name: this.shouldConcealLogs ? smear(f.name) : f.name,
            path: this.shouldConcealLogs ? smearPath(f.path) : f.path,
            reason: f.failReason,
          })),
        });
        return { status: 'migration_failed', error: 'Failed to delete old root scope' };
      }

      this.logger.log(`${logPrefix} Migration completed successfully`);
      return { status: 'migration_completed' };
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Migration failed`,
        error: sanitizeError(error),
      });
      const errorMessage = error instanceof Error ? error.message : String(error);
      return { status: 'migration_failed', error: errorMessage };
    }
  }
}
