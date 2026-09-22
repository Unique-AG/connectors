import {
  BadRequestException,
  ForbiddenException,
  Injectable,
  ServiceUnavailableException,
} from '@nestjs/common';
import { z } from 'zod';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import type { RequestIdentity } from './identity.guard.js';

const assistantSchema = z.object({
  id: z.string().min(1),
  executionProvider: z.enum(['NATIVE', 'A2A']),
});
const capabilitiesSchema = z.object({
  configured: z.boolean(),
  enabled: z.boolean(),
  available: z.boolean(),
  retryable: z.boolean(),
});
const permissionsSchema = z.object({
  uiPermissions: z.object({ canAccessSpaceManagement: z.boolean() }),
});

@Injectable()
export class AuthorizationService {
  public constructor(private readonly unique: UniqueInternalClient) {}

  public async assertNewUse(identity: RequestIdentity): Promise<void> {
    const result = capabilitiesSchema.safeParse(await this.unique.getCapabilities(identity));
    if (!result.success) {
      throw new ServiceUnavailableException('A2A capability information is unavailable');
    }
    const capability = result.data;
    if (!capability.configured || !capability.enabled) {
      throw new ForbiddenException('A2A is not enabled');
    }
    if (!capability.available) {
      throw new ServiceUnavailableException('A2A is temporarily unavailable');
    }
  }

  public async useSpace(identity: RequestIdentity, assistantId: string): Promise<void> {
    this.validateAssistant(await this.unique.getAssistant(identity, assistantId), assistantId);
  }

  public async manageSpace(identity: RequestIdentity, assistantId: string): Promise<void> {
    this.validateAssistant(
      await this.unique.verifySpaceManagement(identity, assistantId),
      assistantId,
    );
  }

  public async publishSpace(identity: RequestIdentity, assistantId: string): Promise<void> {
    await this.assertNewUse(identity);
    const assistant = this.validateAssistant(
      await this.unique.verifySpaceManagement(identity, assistantId),
      assistantId,
    );
    if (assistant.executionProvider === 'A2A') {
      throw new BadRequestException('an A2A-backed space cannot be published');
    }
  }

  public async manageConnections(identity: RequestIdentity): Promise<void> {
    const permissions = permissionsSchema.safeParse(await this.unique.getPermissions(identity));
    if (!permissions.success || !permissions.data.uiPermissions.canAccessSpaceManagement) {
      throw new ForbiddenException('space management access required');
    }
  }

  private validateAssistant(value: unknown, assistantId: string): z.infer<typeof assistantSchema> {
    const assistant = assistantSchema.safeParse(value);
    if (!assistant.success || assistant.data.id !== assistantId) {
      throw new ForbiddenException('space access required');
    }
    return assistant.data;
  }
}
