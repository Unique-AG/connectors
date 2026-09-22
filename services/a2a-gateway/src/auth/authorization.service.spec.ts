import {
  BadRequestException,
  ForbiddenException,
  ServiceUnavailableException,
} from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { AuthorizationService } from './authorization.service.js';

const identity = { companyId: 'company-1', userId: 'user-1', roles: ['ADMIN_SPACE_WRITE'] };
function subject() {
  const unique = {
    getCapabilities: vi
      .fn()
      .mockResolvedValue({ configured: true, enabled: true, available: true, retryable: false }),
    verifySpaceManagement: vi.fn().mockResolvedValue({ id: 'assistant-1' }),
    getAssistant: vi.fn().mockResolvedValue({ id: 'assistant-1' }),
    getPermissions: vi
      .fn()
      .mockResolvedValue({ uiPermissions: { canAccessSpaceManagement: true } }),
  };
  return { unique, service: new AuthorizationService(unique as unknown as UniqueInternalClient) };
}
describe('AuthorizationService', () => {
  it('lets core-authorized managers publish without tenant approval', async () => {
    const { service, unique } = subject();
    await service.publishSpace({ ...identity, roles: [] }, 'assistant-1');
    expect(unique.verifySpaceManagement).toHaveBeenCalledWith(
      { ...identity, roles: [] },
      'assistant-1',
    );
  });
  it('rejects external space publication even when core management access is allowed', async () => {
    const { service, unique } = subject();
    unique.verifySpaceManagement.mockResolvedValue({ id: 'assistant-1', executionProvider: 'A2A' });
    await expect(service.publishSpace(identity, 'assistant-1')).rejects.toBeInstanceOf(
      BadRequestException,
    );
  });
  it('does not use role headers as a substitute for current core access', async () => {
    const { service, unique } = subject();
    unique.getPermissions.mockResolvedValue({ uiPermissions: { canAccessSpaceManagement: false } });
    await expect(service.manageConnections(identity)).rejects.toBeInstanceOf(ForbiddenException);
  });
  it.each([
    { configured: false, enabled: true, available: true, retryable: false },
    { configured: true, enabled: false, available: true, retryable: false },
  ])('fails closed when disabled or not deployed', async (capability) => {
    const { service, unique } = subject();
    unique.getCapabilities.mockResolvedValue(capability);
    await expect(service.assertNewUse(identity)).rejects.toBeInstanceOf(ForbiddenException);
  });
  it('reports an outage as retryable', async () => {
    const { service, unique } = subject();
    unique.getCapabilities.mockResolvedValue({
      configured: true,
      enabled: true,
      available: false,
      retryable: true,
    });
    await expect(service.assertNewUse(identity)).rejects.toBeInstanceOf(
      ServiceUnavailableException,
    );
  });
  it('rejects malformed responses or a different object', async () => {
    const { service, unique } = subject();
    unique.getAssistant.mockResolvedValue({ id: 'other-space' });
    await expect(service.useSpace(identity, 'assistant-1')).rejects.toBeInstanceOf(
      ForbiddenException,
    );
  });
});
