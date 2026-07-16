import type { ConfigService } from '@nestjs/config';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UniqueConfigNamespaced } from '~/config';
import { RootScopeBootstrapService } from './root-scope-bootstrap.service';
import { ScopeAccessEntityType, ScopeAccessType } from './unique.dtos';
import type { UniqueScopeService } from './unique-scope.service';

const rootScopeId = 'scope_root_01';
const serviceUserId = 'user_service_01';

const makeConfig = (unique: Record<string, unknown>) =>
  ({ get: vi.fn().mockReturnValue(unique) }) as unknown as ConfigService<
    UniqueConfigNamespaced,
    true
  >;

const makeService = (
  unique: Record<string, unknown>,
  scopeService: Pick<UniqueScopeService, 'addScopeAccesses'>,
) => new RootScopeBootstrapService(makeConfig(unique), scopeService as UniqueScopeService);

describe('RootScopeBootstrapService', () => {
  let mockScopeService: { addScopeAccesses: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    mockScopeService = { addScopeAccesses: vi.fn().mockResolvedValue(undefined) };
    vi.clearAllMocks();
  });

  it('grants MANAGE/READ/WRITE to the service user on the root scope', async () => {
    const service = makeService(
      { rootScopeId, serviceExtraHeaders: { 'x-user-id': serviceUserId } },
      mockScopeService,
    );

    await service.onApplicationBootstrap();

    expect(mockScopeService.addScopeAccesses).toHaveBeenCalledOnce();
    expect(mockScopeService.addScopeAccesses).toHaveBeenCalledWith(rootScopeId, [
      {
        entityId: serviceUserId,
        entityType: ScopeAccessEntityType.User,
        type: ScopeAccessType.Manage,
      },
      {
        entityId: serviceUserId,
        entityType: ScopeAccessEntityType.User,
        type: ScopeAccessType.Read,
      },
      {
        entityId: serviceUserId,
        entityType: ScopeAccessEntityType.User,
        type: ScopeAccessType.Write,
      },
    ]);
  });

  it('rethrows when the grant fails so startup hard-fails', async () => {
    mockScopeService.addScopeAccesses.mockRejectedValue(new Error('add-access failed'));
    const service = makeService(
      { rootScopeId, serviceExtraHeaders: { 'x-user-id': serviceUserId } },
      mockScopeService,
    );

    await expect(service.onApplicationBootstrap()).rejects.toThrow('add-access failed');
  });

  it('throws the assertion when x-user-id is missing', async () => {
    const service = makeService({ rootScopeId, serviceExtraHeaders: {} }, mockScopeService);

    await expect(service.onApplicationBootstrap()).rejects.toThrow(/x-user-id/);
    expect(mockScopeService.addScopeAccesses).not.toHaveBeenCalled();
  });
});
