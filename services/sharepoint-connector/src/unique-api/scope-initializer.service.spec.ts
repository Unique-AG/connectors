import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ScopeInitializerService } from './scope-initializer.service';
import { UniqueApiService } from './unique-api.service';
import { UniqueAuthService } from './unique-auth.service';

describe('ScopeInitializerService', () => {
  let service: ScopeInitializerService;
  let mockConfigService: Partial<ConfigService>;
  let mockUniqueAuthService: Partial<UniqueAuthService>;
  let mockUniqueApiService: Partial<UniqueApiService>;

  const mockScope = {
    id: 'scope_abc123xyz',
    name: 'LorandTest1',
    externalId: null,
  };

  const mockScopeWithExternalId = {
    id: 'scope_xyz789abc',
    name: 'LorandTest1',
    externalId: 'uniqueapp.sharepoint.com',
  };

  const sharepointBaseUrl = 'uniqueapp.sharepoint.com';

  beforeEach(async () => {
    mockConfigService = {
      get: vi.fn((key: string) => {
        if (key === 'sharepoint.baseUrl') return sharepointBaseUrl;
        return undefined;
      }),
    };

    mockUniqueAuthService = {
      getToken: vi.fn().mockResolvedValue('test-token'),
    };

    mockUniqueApiService = {
      queryRootScopeByName: vi.fn(),
      updateScopeExternalId: vi.fn(),
    };

    const { unit } = await TestBed.solitary(ScopeInitializerService)
      .mock(ConfigService)
      .impl(() => mockConfigService)
      .mock(UniqueAuthService)
      .impl(() => mockUniqueAuthService)
      .mock(UniqueApiService)
      .impl(() => mockUniqueApiService)
      .compile();

    service = unit;
  });

  describe('initialize', () => {
    it('updates scope when externalId is null', async () => {
      (mockUniqueApiService.queryRootScopeByName as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        mockScope,
      );

      await service.initialize('LorandTest1');

      expect(mockUniqueApiService.queryRootScopeByName).toHaveBeenCalledWith('LorandTest1', 'test-token');
      expect(mockUniqueApiService.updateScopeExternalId).toHaveBeenCalledWith(
        'scope_abc123xyz',
        sharepointBaseUrl,
        'test-token',
      );
    });

    it('skips update when scope already has externalId', async () => {
      (mockUniqueApiService.queryRootScopeByName as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        mockScopeWithExternalId,
      );

      await service.initialize('LorandTest1');

      expect(mockUniqueApiService.queryRootScopeByName).toHaveBeenCalledWith('LorandTest1', 'test-token');
      expect(mockUniqueApiService.updateScopeExternalId).not.toHaveBeenCalled();
    });

    it('skips when root scope not found', async () => {
      (mockUniqueApiService.queryRootScopeByName as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);

      await service.initialize('NonExistentScope');

      expect(mockUniqueApiService.queryRootScopeByName).toHaveBeenCalledWith('NonExistentScope', 'test-token');
      expect(mockUniqueApiService.updateScopeExternalId).not.toHaveBeenCalled();
    });

    it('throws error when queryRootScopeByName fails', async () => {
      const testError = new Error('GraphQL query failed');
      (mockUniqueApiService.queryRootScopeByName as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        testError,
      );

      await expect(service.initialize('LorandTest1')).rejects.toThrow('GraphQL query failed');
    });

    it('throws error when updateScopeExternalId fails', async () => {
      (mockUniqueApiService.queryRootScopeByName as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        mockScope,
      );
      const testError = new Error('GraphQL mutation failed');
      (mockUniqueApiService.updateScopeExternalId as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        testError,
      );

      await expect(service.initialize('LorandTest1')).rejects.toThrow('GraphQL mutation failed');
    });

    it('retrieves SharePoint base URL from config', async () => {
      (mockUniqueApiService.queryRootScopeByName as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        mockScope,
      );

      await service.initialize('LorandTest1');

      expect(mockConfigService.get).toHaveBeenCalledWith('sharepoint.baseUrl', { infer: true });
    });

    it('retrieves auth token from UniqueAuthService', async () => {
      (mockUniqueApiService.queryRootScopeByName as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        mockScope,
      );

      await service.initialize('LorandTest1');

      expect(mockUniqueAuthService.getToken).toHaveBeenCalled();
    });
  });
});
