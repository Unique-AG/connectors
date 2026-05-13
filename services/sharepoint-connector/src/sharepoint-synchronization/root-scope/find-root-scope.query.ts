import { Injectable, Logger } from '@nestjs/common';
import { isNullish } from 'remeda';
import { isAutoScope, type SiteConfig } from '../../config/sharepoint.schema';
import { UniqueScopesService } from '../../unique-api/unique-scopes/unique-scopes.service';
import type { Scope } from '../../unique-api/unique-scopes/unique-scopes.types';
import { buildRootExternalId, isOwnedBySite } from '../../utils/scope-external-id';
import { createSmeared, Smeared } from '../../utils/smeared';
import { RootScopeResolutionError } from './root-scope-resolution.error';

@Injectable()
export class FindRootScopeQuery {
  private readonly logger = new Logger(FindRootScopeQuery.name);

  public constructor(private readonly uniqueScopesService: UniqueScopesService) {}

  /**
   * Pure query: returns the existing claimed root scope for a site, or null if no claim exists.
   *
   * Behaviour:
   * - `fixed` rows: returns null. The finder is only meaningful for `auto` rows; the orchestrator
   *   knows the scope id directly for fixed and should not call this method. We short-circuit
   *   instead of throwing so callers can treat finder + provisioner uniformly.
   * - `auto` rows: tries (1) externalId lookup of the claimed root, then (2) listChildrenScopes
   *   of the configured parent scanning for an externalId match (new or legacy format).
   * - When `options.siteName` is provided, also (3) name-matches against children and throws a
   *   typed `RootScopeResolutionError` for unclaimed/foreign/ambiguous matches.
   * - When `options.siteName` is omitted, the name-match step is skipped (deletion/probe mode).
   *
   * Never mutates: a parent-mismatch on a claimed scope is NOT moved here — that is a command
   * and lives in the orchestrator/sync flow.
   */
  public async execute(
    siteConfig: SiteConfig,
    options?: { siteName?: Smeared },
  ): Promise<Scope | null> {
    if (!isAutoScope(siteConfig.scopeId)) {
      return null;
    }

    const { parentScopeId } = siteConfig.scopeId;
    const siteId = siteConfig.siteId;
    const rootExternalId = buildRootExternalId(siteId.value);
    const logPrefix = `[Site: ${siteId}] [Parent: ${parentScopeId}]`;

    const claimedScope = await this.uniqueScopesService.getScopeByExternalId(rootExternalId.value);
    if (claimedScope) {
      this.logger.log(`${logPrefix} Found claimed root scope ${claimedScope.id} by externalId`);
      return claimedScope;
    }

    const children = await this.uniqueScopesService.listChildrenScopes(parentScopeId);

    const externalIdMatch = children.find((child) => isOwnedBySite(child, siteId.value));
    if (externalIdMatch) {
      this.logger.log(
        `${logPrefix} Found existing child scope ${externalIdMatch.id} matched by legacy externalId`,
      );
      return externalIdMatch;
    }

    if (isNullish(options?.siteName)) {
      return null;
    }

    const siteName = options.siteName;
    const nameMatches = children.filter((child) => child.name === siteName.value);
    if (nameMatches.length > 1) {
      throw new RootScopeResolutionError('ambiguous_name_match', {
        siteId: siteId.value,
        parentScopeId,
        siteName,
        detail: `${nameMatches.length} children of parent share the configured site name`,
      });
    }

    const [nameMatch] = nameMatches;
    if (isNullish(nameMatch)) {
      return null;
    }

    if (isNullish(nameMatch.externalId)) {
      throw new RootScopeResolutionError('unclaimed_name_match', {
        siteId: siteId.value,
        parentScopeId,
        siteName,
        detail: `child scope ${nameMatch.id} matches by name but has no externalId; refusing to claim`,
      });
    }

    throw new RootScopeResolutionError('foreign_name_match', {
      siteId: siteId.value,
      parentScopeId,
      siteName,
      detail: `child scope ${nameMatch.id} matches by name but is owned by externalId ${createSmeared(nameMatch.externalId)}`,
    });
  }
}
