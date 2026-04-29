import { Injectable, Logger } from '@nestjs/common';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { sanitizeError } from '../utils/normalize-error';
import { buildRootExternalId, EXTERNAL_ID_PREFIX } from '../utils/scope-external-id';
import { createSmeared, Smeared, smearPath } from '../utils/smeared';

export type MigrationResult =
  | { status: 'no_migration_needed' }
  | { status: 'migration_completed' }
  | { status: 'migration_failed'; error: string };

@Injectable()
export class RootScopeMigrationService {
  private readonly logger = new Logger(RootScopeMigrationService.name);

  public constructor(private readonly uniqueScopesService: UniqueScopesService) {}

  public async migrateIfNeeded(newRootScopeId: string, siteId: Smeared): Promise<MigrationResult> {
    const legacyExternalId = `${EXTERNAL_ID_PREFIX}site:${siteId.value}`;
    const newFormatExternalId = buildRootExternalId(siteId.value).value;
    const logPrefix = `[Migration: ${siteId}]`;

    try {
      // Try the legacy format first, then fall back to the new format. The fallback is required
      // because `ScopeExternalIdMigrationService` runs earlier in `initializeRootScope` and
      // rewrites any legacy `spc:site:{id}` root to `spc:{id}/site` before this service is
      // called. Without the fallback, a user who reconfigures `rootScopeId` after the externalId
      // migration has run would leave children stranded under the old root because the legacy
      // lookup would always miss.
      const oldRoot =
        (await this.uniqueScopesService.getScopeByExternalId(legacyExternalId)) ??
        (await this.uniqueScopesService.getScopeByExternalId(newFormatExternalId));

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

      // TODO: flat-mode root migration is not handled here. In flat mode the old
      // root holds content items directly; before touching the old root the migration
      // must either list those items and include them as `contentIds` in the bulk
      // move, or switch the delete below to `recursive: true` once content has been
      // re-owned to the new root. Tracked as a follow-up.
      if (children.length > 0) {
        /*
          Depending on the number of files it has to move, bulkMove can be a sync operation or an async operation.
          But it always returns *after the new parent was correctly set for scopes and files*.
          What it actually does asynchronously is themetadata update where it computes the new folderIdPath, for example
           - folderIdpath: "uniquepathid://scope_o5jr5ig8k4iugk8lhd8nq42e/scope_xrqbd1pjg71xq7o6r762w01o"
          Recomputing the metadata is a slower process that's why for more files (default is 10) it'll be async
         */
        await this.uniqueScopesService.bulkMoveScopes(
          children.map((c) => c.id),
          newRootScopeId,
        );
        this.logger.log(`${logPrefix} Moved ${children.length} children to new root`);
      }

      this.logger.log(`${logPrefix} Deleting old root scope ${oldRoot.id}`);
      const result = await this.uniqueScopesService.deleteScope(oldRoot.id);

      if (result.failedFolders.length > 0) {
        this.logger.warn({
          msg: `${logPrefix} Failed to delete old root due to ${result.failedFolders.length} folders`,
          failedFolders: result.failedFolders.map((f) => ({
            id: f.id,
            name: createSmeared(f.name),
            path: smearPath(createSmeared(f.path)),
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
