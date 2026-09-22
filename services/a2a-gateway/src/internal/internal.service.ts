import { Injectable } from '@nestjs/common';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { PublicationRepository } from '../drizzle/publication.repository.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { UniqueInternalError } from '../unique/unique-internal.error.js';

export interface PublicationReconciliation {
  assistantId: string;
  executionProvider?: 'NATIVE' | 'A2A';
  deleted: boolean;
}

@Injectable()
export class InternalService {
  public constructor(
    private readonly publications: PublicationRepository,
    private readonly unique: UniqueInternalClient,
  ) {}

  public async reconcilePublication(
    identity: RequestIdentity,
    reconciliation: PublicationReconciliation,
  ): Promise<void> {
    try {
      const assistant = await this.unique.verifySpaceManagement(
        identity,
        reconciliation.assistantId,
      );
      if (
        typeof assistant === 'object' &&
        assistant !== null &&
        Reflect.get(assistant, 'executionProvider') === 'A2A'
      ) {
        await this.publications.disable(identity.companyId, reconciliation.assistantId);
      }
    } catch (error) {
      if (!(error instanceof UniqueInternalError) || error.code !== 'NOT_FOUND') {
        throw error;
      }
      await this.publications.disable(identity.companyId, reconciliation.assistantId);
    }
  }
}
