import { Injectable, Logger } from '@nestjs/common';

export interface AuditActor {
  companyId: string;
  userId?: string;
}

/**
 * Security-relevant actions as structured, content-free log records (`audit: true`): ids and
 * outcomes only, never prompts, answers, file names, tokens or credentials.
 */
@Injectable()
export class AuditLog {
  private readonly logger = new Logger('Audit');

  public record(
    action: string,
    actor: AuditActor,
    details: Record<string, string | number | boolean | undefined> = {},
  ): void {
    this.logger.log({
      audit: true,
      action,
      companyId: actor.companyId,
      userId: actor.userId,
      ...details,
    });
  }
}
