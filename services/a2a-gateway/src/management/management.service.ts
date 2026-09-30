import { Injectable, NotFoundException } from '@nestjs/common';
import { AuthorizationService } from '../auth/authorization.service.js';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { PublicationRepository } from '../drizzle/publication.repository.js';
import { AuditLog } from '../observability/audit-log.service.js';
import type { PublicationConfiguration } from './publication-configuration.js';

@Injectable()
export class ManagementService {
  public constructor(
    private readonly publications: PublicationRepository,
    private readonly authorization: AuthorizationService,
    private readonly audit: AuditLog,
  ) {}

  public async getPublication(identity: RequestIdentity, assistantId: string) {
    await this.authorization.manageSpace(identity, assistantId);
    const publication = await this.publications.findByAssistant(identity.companyId, assistantId);
    if (!publication) {
      throw new NotFoundException('publication not found');
    }
    return publication;
  }

  public async putPublication(
    identity: RequestIdentity,
    assistantId: string,
    configuration: PublicationConfiguration,
    expectedVersion?: number,
  ) {
    await this.authorization.publishSpace(identity, assistantId);
    const publication = await this.publications.upsert(
      identity,
      {
        assistantId,
        enabled: configuration.enabled,
        cardOverrides: configuration.card,
        skills: configuration.skills,
      },
      expectedVersion,
    );
    this.audit.record('publication.configure', identity, { assistantId });
    return publication;
  }

  public async disablePublication(identity: RequestIdentity, assistantId: string): Promise<void> {
    await this.authorization.manageSpace(identity, assistantId);
    await this.publications.disable(identity.companyId, assistantId);
    this.audit.record('publication.disable', identity, { assistantId });
  }
}
