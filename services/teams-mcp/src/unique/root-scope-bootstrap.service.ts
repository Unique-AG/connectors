import assert from 'node:assert';
import { Injectable, Logger, type OnApplicationBootstrap } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { UniqueConfigNamespaced } from '~/config';
import { normalizeError } from '~/utils/normalize-error';
import { ScopeAccessEntityType, ScopeAccessType } from './unique.dtos';
import { UniqueScopeService } from './unique-scope.service';

/**
 * Self-grants the service user MANAGE/READ/WRITE on the configured root scope at
 * startup. Ingestion assumes the service user already owns the root scope so it
 * can create sub-scopes and grant access under it; this hook makes a
 * misconfiguration crash the pod at boot instead of surfacing as an opaque
 * platform error mid-ingestion.
 */
@Injectable()
export class RootScopeBootstrapService implements OnApplicationBootstrap {
  private readonly logger = new Logger(RootScopeBootstrapService.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly scopeService: UniqueScopeService,
  ) {}

  public async onApplicationBootstrap(): Promise<void> {
    const { rootScopeId, serviceExtraHeaders } = this.config.get('unique', { infer: true });
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
