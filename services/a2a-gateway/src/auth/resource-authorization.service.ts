import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { DRIZZLE, type GatewayDatabase } from '../drizzle/drizzle.module.js';
import { contexts } from '../drizzle/schema/contexts.table.js';
import { publications } from '../drizzle/schema/publications.table.js';
import { UniqueInternalError } from '../unique/unique-internal.client.js';
import { AuthorizationService } from './authorization.service.js';
import type { RequestIdentity } from './identity.guard.js';

@Injectable()
export class ResourceAuthorizationService {
  public constructor(
    @Inject(DRIZZLE) private readonly database: GatewayDatabase,
    private readonly authorization: AuthorizationService,
  ) {}

  public async publication(
    identity: RequestIdentity,
    publicationId: string,
    newUse = false,
  ): Promise<void> {
    const publication = await this.database.query.publications.findFirst({
      where: and(
        eq(publications.companyId, identity.companyId),
        eq(publications.id, publicationId),
      ),
    });
    if (!publication || (newUse && !publication.enabled)) {
      throw new NotFoundException('publication not found');
    }
    try {
      await this.authorization.useSpace(identity, publication.assistantId);
    } catch (error) {
      if (
        error instanceof UniqueInternalError &&
        ['NOT_FOUND', 'UNAUTHORIZED'].includes(error.code)
      ) {
        throw new NotFoundException('publication not found');
      }
      throw error;
    }
    if (newUse) {
      await this.authorization.assertNewUse(identity);
    }
  }

  public async context(
    identity: RequestIdentity,
    publicationId: string,
    contextId: string,
  ): Promise<void> {
    const context = await this.database.query.contexts.findFirst({
      where: and(
        eq(contexts.companyId, identity.companyId),
        eq(contexts.userId, identity.userId),
        eq(contexts.id, contextId),
        eq(contexts.publicationId, publicationId),
      ),
    });
    if (!context) {
      throw new NotFoundException('context not found');
    }
    await this.publication(identity, publicationId);
  }
}
