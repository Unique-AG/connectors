import { isDeepStrictEqual } from 'node:util';
import { ConflictException, Inject, Injectable } from '@nestjs/common';
import { and, eq, sql } from 'drizzle-orm';

import { DRIZZLE, type GatewayDatabase } from './drizzle.module.js';
import type { TenantPrincipal } from './repository.types.js';
import { publications } from './schema/publications.table.js';
import { isUniqueViolation } from './unique-violation.js';

export interface PublicationWrite {
  assistantId: string;
  enabled: boolean;
  cardOverrides?: Record<string, unknown>;
  skills?: unknown[];
}

@Injectable()
export class PublicationRepository {
  public constructor(@Inject(DRIZZLE) private readonly database: GatewayDatabase) {}

  public async findByAssistant(companyId: string, assistantId: string) {
    return this.database.query.publications.findFirst({
      where: and(eq(publications.companyId, companyId), eq(publications.assistantId, assistantId)),
    });
  }

  public async findById(companyId: string, publicationId: string) {
    return this.database.query.publications.findFirst({
      where: and(eq(publications.companyId, companyId), eq(publications.id, publicationId)),
    });
  }

  public async findEnabledById(publicationId: string) {
    return this.database.query.publications.findFirst({
      where: and(eq(publications.id, publicationId), eq(publications.enabled, true)),
    });
  }

  public async listEnabled(companyId: string) {
    return this.database.query.publications.findMany({
      where: and(eq(publications.companyId, companyId), eq(publications.enabled, true)),
    });
  }

  public async upsert(principal: TenantPrincipal, input: PublicationWrite, expectedVersion?: number) {
    const existing = await this.findByAssistant(principal.companyId, input.assistantId);
    if (
      existing &&
      isDeepStrictEqual(
        { enabled: existing.enabled, cardOverrides: existing.cardOverrides, skills: existing.skills },
        JSON.parse(
          JSON.stringify({
            enabled: input.enabled,
            cardOverrides: input.cardOverrides ?? {},
            skills: input.skills ?? [],
          }),
        ),
      )
    ) {
      return existing;
    }
    if (existing && expectedVersion !== existing.version) {
      throw new ConflictException('publication version does not match If-Match');
    }
    if (!existing) {
      try {
        const [created] = await this.database
          .insert(publications)
          .values({ companyId: principal.companyId, createdByUserId: principal.userId, ...input })
          .returning();
        return created;
      } catch (error) {
        if (isUniqueViolation(error, 'a2a_publications_company_assistant_unique')) {
          throw new ConflictException('publication was created concurrently');
        }
        throw error;
      }
    }
    const [updated] = await this.database
      .update(publications)
      .set({
        enabled: input.enabled,
        cardOverrides: input.cardOverrides ?? {},
        skills: input.skills ?? [],
        disabledAt: input.enabled ? null : new Date(),
        version: sql`${publications.version} + 1`,
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(publications.id, existing.id),
          eq(publications.companyId, principal.companyId),
          eq(publications.version, existing.version),
        ),
      )
      .returning();
    if (!updated) {
      throw new ConflictException('publication was modified concurrently');
    }
    return updated;
  }

  public async disable(companyId: string, assistantId: string): Promise<void> {
    await this.database
      .update(publications)
      .set({
        enabled: false,
        disabledAt: new Date(),
        version: sql`${publications.version} + 1`,
        updatedAt: new Date(),
      })
      .where(and(eq(publications.companyId, companyId), eq(publications.assistantId, assistantId)));
  }
}
