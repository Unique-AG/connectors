import { Inject, Injectable, Logger, type OnModuleInit } from '@nestjs/common';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { PublicationRepository } from '../drizzle/publication.repository.js';
import { RetentionRepository } from '../drizzle/retention.repository.js';
import { AuditLog } from '../observability/audit-log.service.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { UniqueInternalError } from '../unique/unique-internal.error.js';
import { MaintenanceService } from '../workflow/maintenance.service.js';

const BATCH = 500;
const RECONCILE_BATCH = 100;
const UNBOUND_CONNECTION_GRACE_MS = 24 * 3_600_000;

/**
 * Retention of gateway-owned state and reconciliation of publications with core. Runs on the
 * replica-independent maintenance loop; access itself is always re-authorized live, so a missed
 * reconciliation never grants access.
 */
@Injectable()
export class LifecycleService implements OnModuleInit {
  private readonly logger = new Logger(LifecycleService.name);
  private publicationCursor = '';

  public constructor(
    private readonly retention: RetentionRepository,
    private readonly publications: PublicationRepository,
    private readonly unique: UniqueInternalClient,
    private readonly maintenance: MaintenanceService,
    private readonly audit: AuditLog,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public onModuleInit(): void {
    this.maintenance.register('lifecycle.retention', () => this.purge());
    this.maintenance.register('lifecycle.reconcile-publications', () =>
      this.reconcilePublications(),
    );
  }

  public async purge(): Promise<void> {
    const now = new Date();
    const idleBefore = new Date(now.getTime() - this.config.taskRetentionDays * 86_400_000);
    const purged = {
      tasks: await this.retention.purgeTasks(now, BATCH),
      contexts: await this.retention.purgeContexts(idleBefore, BATCH),
      executions: await this.retention.purgeExecutions(now, BATCH),
      remoteContexts: await this.retention.purgeRemoteContexts(idleBefore, BATCH),
      connections: await this.retention.purgeUnboundConnections(
        new Date(now.getTime() - UNBOUND_CONNECTION_GRACE_MS),
        BATCH,
      ),
    };
    if (Object.values(purged).some((count) => count > 0)) {
      this.logger.log({ action: 'retention.purge', ...purged });
    }
  }

  /** Disables publications whose space core no longer knows; other failures change nothing. */
  public async reconcilePublications(): Promise<void> {
    const batch = await this.retention.enabledPublications(this.publicationCursor, RECONCILE_BATCH);
    this.publicationCursor = batch.length === RECONCILE_BATCH ? (batch.at(-1)?.id ?? '') : '';
    for (const publication of batch) {
      const identity = {
        companyId: publication.companyId,
        userId: publication.createdByUserId,
        roles: [],
      };
      try {
        await this.unique.verifySpaceManagement(identity, publication.assistantId);
      } catch (error) {
        if (error instanceof UniqueInternalError && error.code === 'NOT_FOUND') {
          await this.publications.disable(publication.companyId, publication.assistantId);
          this.audit.record(
            'publication.reconcile-disable',
            { companyId: publication.companyId },
            {
              publicationId: publication.id,
              assistantId: publication.assistantId,
            },
          );
        }
      }
    }
  }
}
