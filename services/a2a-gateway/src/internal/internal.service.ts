import { Injectable } from '@nestjs/common';
import { PublicationRepository } from '../drizzle/gateway.repository.js';

export interface PublicationReconciliation {
  assistantId: string;
  executionProvider?: 'NATIVE' | 'A2A';
  deleted: boolean;
}

@Injectable()
export class InternalService {
  public constructor(private readonly publications: PublicationRepository) {}

  public async reconcilePublication(
    companyId: string,
    reconciliation: PublicationReconciliation,
  ): Promise<void> {
    if (reconciliation.deleted || reconciliation.executionProvider === 'A2A') {
      await this.publications.disable(companyId, reconciliation.assistantId);
    }
  }
}
