import { describe, expect, it, vi } from 'vitest';
import type { PublicationRepository } from '../drizzle/gateway.repository.js';
import {
  type UniqueInternalClient,
  UniqueInternalError,
} from '../unique/unique-internal.client.js';
import { InternalService } from './internal.service.js';

const identity = { companyId: 'company-1', userId: 'user-1', roles: [] };
function subject() {
  const publications = { disable: vi.fn() };
  const unique = { verifySpaceManagement: vi.fn().mockResolvedValue({ id: 'space-1' }) };
  return {
    publications,
    unique,
    service: new InternalService(
      publications as unknown as PublicationRepository,
      unique as unknown as UniqueInternalClient,
    ),
  };
}
describe('publication reconciliation', () => {
  it('does not trust caller-supplied deletion/provider state', async () => {
    const { service, publications } = subject();
    await service.reconcilePublication(identity, {
      assistantId: 'space-1',
      deleted: true,
      executionProvider: 'A2A',
    });
    expect(publications.disable).not.toHaveBeenCalled();
  });
  it('disables a publication only when core confirms the space is missing', async () => {
    const { service, unique, publications } = subject();
    unique.verifySpaceManagement.mockRejectedValue(
      new UniqueInternalError('missing', 'NOT_FOUND', false),
    );
    await service.reconcilePublication(identity, { assistantId: 'space-1', deleted: true });
    expect(publications.disable).toHaveBeenCalledWith('company-1', 'space-1');
  });
  it('does not treat an outage or denied permission as deletion', async () => {
    const { service, unique, publications } = subject();
    unique.verifySpaceManagement.mockRejectedValue(
      new UniqueInternalError('unavailable', 'UNAVAILABLE', true),
    );
    await expect(
      service.reconcilePublication(identity, { assistantId: 'space-1', deleted: true }),
    ).rejects.toBeInstanceOf(UniqueInternalError);
    expect(publications.disable).not.toHaveBeenCalled();
  });
});
