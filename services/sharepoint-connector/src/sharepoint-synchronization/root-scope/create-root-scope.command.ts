import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { isAutoScope, type SiteConfig } from '../../config/sharepoint.schema';
import { UniqueScopesService } from '../../unique-api/unique-scopes/unique-scopes.service';
import { UniqueUsersService } from '../../unique-api/unique-users/unique-users.service';
import { sanitizeError } from '../../utils/normalize-error';
import { buildRootExternalId } from '../../utils/scope-external-id';
import { createSmeared, Smeared, smearPath } from '../../utils/smeared';
import { ResolveScopePathCommand } from './resolve-scope-path.command';
import { RootScopeResolutionError } from './root-scope-resolution.error';

@Injectable()
export class CreateRootScopeCommand {
  private readonly logger = new Logger(CreateRootScopeCommand.name);

  public constructor(
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly uniqueUsersService: UniqueUsersService,
    private readonly resolveScopePathCommand: ResolveScopePathCommand,
  ) {}

  /**
   * Pure command: creates a new root scope under the configured parent and claims it with the
   * site's externalId. Only valid for `auto` rows; throws a typed `RootScopeResolutionError` with
   * code `invalid_scope_kind` if called with a `fixed` config so callers that uniformly catch
   * `RootScopeResolutionError` can handle the misuse alongside other resolution failures.
   */
  public async execute(
    siteConfig: SiteConfig,
    siteName: Smeared,
  ): Promise<{ rootScopeId: string; rootPath: Smeared }> {
    if (!isAutoScope(siteConfig.scopeId)) {
      throw new RootScopeResolutionError('invalid_scope_kind', {
        siteId: siteConfig.siteId.value,
        detail: 'CreateRootScopeCommand.execute called with fixed scopeId; expected auto',
      });
    }

    const { parentScopeId } = siteConfig.scopeId;
    const siteId = siteConfig.siteId;
    const rootExternalId = buildRootExternalId(siteId.value);
    const logPrefix = `[Site: ${siteId}] [Parent: ${parentScopeId}]`;

    if (siteName.value.length === 0) {
      throw new RootScopeResolutionError('invalid_site_name', {
        siteId: siteId.value,
        parentScopeId,
        siteName,
        detail: 'siteName must be a non-empty path',
      });
    }

    const userId = await this.uniqueUsersService.getCurrentUserId();
    assert.ok(userId, 'User ID must be available');

    // Grant READ on the parent first so we can read it on a fresh deployment where the service
    // user has no implicit visibility.
    await this.uniqueScopesService.createScopeAccesses(parentScopeId, [
      { type: 'READ', entityId: userId, entityType: 'USER' },
    ]);

    const parentScope = await this.uniqueScopesService.getScopeById(parentScopeId);
    if (!parentScope) {
      throw new RootScopeResolutionError('invalid_parent', {
        siteId: siteId.value,
        parentScopeId,
        siteName,
        detail: `configured parent scope ${parentScopeId} not found`,
      });
    }

    const parentPath = await this.resolveScopePathCommand.execute(parentScope, userId);
    const newPath = createSmeared(`${parentPath.value}/${siteName.value}`);

    this.logger.log(`${logPrefix} Creating new root scope at path ${newPath}`);
    const createdScopes = await this.uniqueScopesService.createScopesBasedOnPaths([newPath.value], {
      includePermissions: true,
      inheritAccess: false,
    });

    // The contract assumed throughout the codebase (see `batchCreateScopes` in
    // `scope-management.service.ts`) is positional: one input path → one output scope. Asserting
    // the length explicitly defends against silent contract drift (e.g. the API starting to return
    // intermediate parent scopes alongside the requested one), which would otherwise cause the
    // downstream parent-mismatch rollback to delete the wrong scope.
    if (createdScopes.length !== 1) {
      const detail =
        `${logPrefix} createScopesBasedOnPaths returned ${createdScopes.length} scopes for a ` +
        `single-path request (path ${smearPath(newPath)}); expected exactly 1`;
      // Roll back every returned scope — we can't safely identify which one is "ours".
      for (const scope of createdScopes) {
        await this.rollbackCreatedScope(scope.id, logPrefix);
      }
      throw new RootScopeResolutionError('claim_failed', {
        siteId: siteId.value,
        parentScopeId,
        siteName,
        detail,
      });
    }

    const created = createdScopes[0];
    assert.ok(created, `createScopesBasedOnPaths returned no scope for path ${smearPath(newPath)}`);

    if (created.parentId !== parentScopeId) {
      const detail =
        `${logPrefix} createScopesBasedOnPaths returned scope ${created.id} under unexpected ` +
        `parent ${created.parentId ?? 'null'} (expected ${parentScopeId})`;
      await this.rollbackCreatedScope(created.id, logPrefix);
      throw new RootScopeResolutionError('claim_failed', {
        siteId: siteId.value,
        parentScopeId,
        siteName,
        detail,
      });
    }

    try {
      await this.uniqueScopesService.updateScopeExternalId(created.id, rootExternalId);
      this.logger.log(
        `${logPrefix} Claimed new root scope ${created.id} with externalId ${rootExternalId.value}`,
      );
      return { rootScopeId: created.id, rootPath: newPath };
    } catch (claimError) {
      this.logger.error({
        msg: `${logPrefix} Failed to claim newly-created root scope ${created.id}; rolling back`,
        error: sanitizeError(claimError),
      });
      await this.rollbackCreatedScope(created.id, logPrefix);
      throw new RootScopeResolutionError('claim_failed', {
        siteId: siteId.value,
        parentScopeId,
        siteName,
        detail: `failed to set externalId on newly-created scope ${created.id}`,
        cause: claimError,
      });
    }
  }

  private async rollbackCreatedScope(scopeId: string, logPrefix: string): Promise<void> {
    try {
      await this.uniqueScopesService.deleteScope(scopeId, { recursive: true });
    } catch (rollbackError) {
      this.logger.error({
        msg: `${logPrefix} Failed to roll back newly-created root scope ${scopeId}`,
        error: sanitizeError(rollbackError),
      });
    }
  }
}
