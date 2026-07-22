import assert from 'node:assert';
import { Inject, Injectable, Logger, type OnApplicationBootstrap } from '@nestjs/common';
import type { EnabledUniqueConfig } from '~/config';
import { KB_INTEGRATION_ENABLED_CONFIG } from '~/kb-integration/kb-integration-config.module';
import { normalizeError } from '~/utils/normalize-error';
import { ScopeAccessEntityType, ScopeAccessType } from './unique.dtos';
import { UniqueScopeService } from './unique-scope.service';

/**
 * (Re-)grants the service user MANAGE/READ/WRITE on the configured root scope at
 * startup. Ingestion assumes the service user already owns the root scope so it
 * can create sub-scopes and grant access under it; this hook enforces that
 * assumption at boot, making a misconfiguration crash the pod immediately
 * instead of surfacing as an opaque platform error mid-ingestion.
 *
 * The grant goes through the Public API `folder/add-access`, which is additive —
 * re-affirming access the service user already has is safe on every boot. It is
 * not a from-zero provisioner: granting still requires the service user to be
 * permitted to manage the scope (the manual grant documented in the operator
 * configuration guide), so a truly unconfigured root scope fails fast here.
 *
 * Only runs when UniqueModule is loaded (UNIQUE_INTEGRATION=enabled).
 */
@Injectable()
export class RootScopeBootstrapService implements OnApplicationBootstrap {
  private readonly logger = new Logger(RootScopeBootstrapService.name);

  public constructor(
    @Inject(KB_INTEGRATION_ENABLED_CONFIG) private readonly config: EnabledUniqueConfig,
    private readonly scopeService: UniqueScopeService,
  ) {}

  public async onApplicationBootstrap(): Promise<void> {
    const { rootScopeId, serviceExtraHeaders } = this.config;
    const serviceUserId = serviceExtraHeaders['x-user-id'];
    // The config schema already requires x-user-id in both auth modes; this guards
    // that invariant before we build the access grants.
    assert.ok(serviceUserId, 'serviceExtraHeaders must contain an x-user-id header');

    const accessTypes = [ScopeAccessType.Manage, ScopeAccessType.Read, ScopeAccessType.Write];

    try {
      await this.scopeService.addScopeAccesses(
        rootScopeId,
        accessTypes.map((type) => ({
          entityId: serviceUserId,
          entityType: ScopeAccessEntityType.User,
          type,
        })),
      );
    } catch (error) {
      this.logger.error(
        { scopeId: rootScopeId, error: normalizeError(error) },
        `root scope ${rootScopeId} permission bootstrap failed`,
      );
      // Rethrow so onApplicationBootstrap rejects and Nest crashes the process:
      // a service user without root-scope access cannot ingest anything.
      throw error;
    }

    this.logger.log(
      { scopeId: rootScopeId, accessTypes },
      'root scope permission bootstrap succeeded',
    );
  }
}
