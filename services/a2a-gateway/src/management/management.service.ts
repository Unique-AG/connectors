import { BadRequestException, Injectable } from '@nestjs/common';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { PublicationRepository } from '../drizzle/gateway.repository.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';

export interface PublicationConfiguration {
  enabled: boolean;
  card: Record<string, unknown>;
  skills: unknown[];
}

function isExternalAssistant(value: unknown): boolean {
  return (
    typeof value === 'object' && value !== null && Reflect.get(value, 'executionProvider') === 'A2A'
  );
}

@Injectable()
export class ManagementService {
  public constructor(
    private readonly publications: PublicationRepository,
    private readonly unique: UniqueInternalClient,
  ) {}

  public getPublication(companyId: string, assistantId: string) {
    return this.publications.findByAssistant(companyId, assistantId);
  }

  public async putPublication(
    identity: RequestIdentity,
    assistantId: string,
    configuration: PublicationConfiguration,
    expectedVersion?: number,
  ) {
    const assistant = await this.unique.getAssistant(identity, assistantId);
    if (isExternalAssistant(assistant)) {
      throw new BadRequestException('an A2A-backed space cannot be published');
    }
    return this.publications.upsert(
      identity,
      {
        assistantId,
        enabled: configuration.enabled,
        cardOverrides: configuration.card,
        skills: configuration.skills,
      },
      expectedVersion,
    );
  }

  public disablePublication(companyId: string, assistantId: string): Promise<void> {
    return this.publications.disable(companyId, assistantId);
  }
}
