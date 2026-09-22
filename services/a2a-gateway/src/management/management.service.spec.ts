import { ForbiddenException } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import type { AuthorizationService } from '../auth/authorization.service.js';
import type { PublicationRepository } from '../drizzle/publication.repository.js';
import { ManagementService } from './management.service.js';

const identity = { companyId: 'company-1', userId: 'user-1', roles: [] };
const configuration = {
  enabled: true,
  card: { name: 'Published space', description: 'Description' },
  skills: [],
};
function subject() {
  const publications = {
    upsert: vi.fn(),
    findByAssistant: vi.fn().mockResolvedValue({ id: 'pub-1' }),
    disable: vi.fn(),
  };
  const authorization = { publishSpace: vi.fn(), manageSpace: vi.fn() };
  return {
    service: new ManagementService(
      publications as unknown as PublicationRepository,
      authorization as unknown as AuthorizationService,
    ),
    publications,
    authorization,
  };
}
describe('ManagementService', () => {
  it('checks publication authorization on every write and does not persist denied writes', async () => {
    const { service, authorization, publications } = subject();
    await service.putPublication(identity, 'assistant-1', configuration);
    authorization.publishSpace.mockRejectedValue(new ForbiddenException());
    await expect(
      service.putPublication(identity, 'assistant-1', configuration, 1),
    ).rejects.toBeInstanceOf(ForbiddenException);
    expect(publications.upsert).toHaveBeenCalledTimes(1);
    expect(authorization.publishSpace).toHaveBeenCalledTimes(2);
  });
  it('checks access on reads and disable even without a feature gate', async () => {
    const { service, authorization, publications } = subject();
    await service.getPublication(identity, 'assistant-1');
    await service.disablePublication(identity, 'assistant-1');
    expect(authorization.manageSpace).toHaveBeenCalledTimes(2);
    expect(publications.disable).toHaveBeenCalledWith('company-1', 'assistant-1');
    expect(authorization.publishSpace).not.toHaveBeenCalled();
  });
});
