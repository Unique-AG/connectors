import { NotFoundException } from '@nestjs/common';
import { PgDialect } from 'drizzle-orm/pg-core';
import { describe, expect, it, vi } from 'vitest';
import type { GatewayDatabase } from '../drizzle/drizzle.module.js';
import { UniqueInternalError } from '../unique/unique-internal.client.js';
import type { AuthorizationService } from './authorization.service.js';
import { ResourceAuthorizationService } from './resource-authorization.service.js';

const identity = { companyId: 'company-1', userId: 'user-1', roles: [] };
function subject() {
  const contexts = { findFirst: vi.fn().mockResolvedValue({ id: 'ctx-1' }) };
  const publications = {
    findFirst: vi.fn().mockResolvedValue({ assistantId: 'space-1', enabled: true }),
  };
  const authorization = { useSpace: vi.fn(), assertNewUse: vi.fn() };
  return {
    contexts,
    publications,
    authorization,
    service: new ResourceAuthorizationService(
      { query: { contexts, publications } } as unknown as GatewayDatabase,
      authorization as unknown as AuthorizationService,
    ),
  };
}
describe('ResourceAuthorizationService', () => {
  it('scopes context reuse to tenant, owner and route publication', async () => {
    const { service, contexts, publications } = subject();
    await service.context(identity, 'pub-1', 'ctx-1');
    const contextWhere = contexts.findFirst.mock.calls[0]?.[0]?.where;
    const publicationWhere = publications.findFirst.mock.calls[0]?.[0]?.where;
    expect(new PgDialect().sqlToQuery(contextWhere).params).toEqual([
      'company-1',
      'user-1',
      'ctx-1',
      'pub-1',
    ]);
    expect(new PgDialect().sqlToQuery(publicationWhere).params).toEqual(['company-1', 'pub-1']);
  });
  it('does not expose cross-owner, cross-company or cross-publication contexts', async () => {
    const { service, contexts, authorization } = subject();
    contexts.findFirst.mockResolvedValue(undefined);
    await expect(service.context(identity, 'pub-other', 'ctx-other')).rejects.toBeInstanceOf(
      NotFoundException,
    );
    expect(authorization.useSpace).not.toHaveBeenCalled();
  });
  it('rechecks current permissions even for an existing catalog entry', async () => {
    const { service, authorization } = subject();
    await service.publication(identity, 'pub-1');
    authorization.useSpace.mockRejectedValue(
      new UniqueInternalError('denied', 'UNAUTHORIZED', false),
    );
    await expect(service.publication(identity, 'pub-1')).rejects.toBeInstanceOf(NotFoundException);
  });
  it('permits authorized existing-task access after disable but refuses new use', async () => {
    const { service, publications, authorization } = subject();
    publications.findFirst.mockResolvedValue({ assistantId: 'space-1', enabled: false });
    await service.context(identity, 'pub-1', 'ctx-1');
    expect(authorization.useSpace).toHaveBeenCalled();
    expect(authorization.assertNewUse).not.toHaveBeenCalled();
    await expect(service.publication(identity, 'pub-1', true)).rejects.toBeInstanceOf(
      NotFoundException,
    );
  });
});
