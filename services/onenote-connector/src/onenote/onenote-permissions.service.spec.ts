import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ScopeAccessEntityType, ScopeAccessType } from '~/unique/unique.dtos';
import type { DrivePermission } from './onenote.types';
import { OneNoteGraphService } from './onenote-graph.service';
import { OneNotePermissionsService } from './onenote-permissions.service';

describe('OneNotePermissionsService', () => {
  const mockConfig = {
    get: vi.fn().mockReturnValue(5),
  };

  const mockGraphService = {
    getGroupMembers: vi.fn(),
  } as unknown as OneNoteGraphService;

  const mockUserService = {
    findUserByEmail: vi.fn(),
  };

  const mockClient = {} as never;

  let service: OneNotePermissionsService;

  beforeEach(() => {
    vi.clearAllMocks();
    // biome-ignore lint/suspicious/noExplicitAny: Test mock
    service = new OneNotePermissionsService(
      mockConfig as any,
      mockGraphService,
      mockUserService as any,
    );
  });

  describe('resolveNotebookAccesses', () => {
    it('resolves user permissions from grantedToV2', async () => {
      const permissions: DrivePermission[] = [
        {
          id: 'perm-1',
          roles: ['read'],
          grantedToV2: { user: { email: 'reader@example.com', id: 'graph-user-1' } },
        },
      ];

      mockUserService.findUserByEmail.mockResolvedValue({ id: 'unique-user-1' });

      const result = await service.resolveNotebookAccesses(mockClient, permissions);

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({
        entityId: 'unique-user-1',
        entityType: ScopeAccessEntityType.User,
        type: ScopeAccessType.Read,
      });
    });

    it('grants owner Read/Write/Manage access', async () => {
      const permissions: DrivePermission[] = [];

      mockUserService.findUserByEmail.mockResolvedValue({ id: 'unique-owner-1' });

      const result = await service.resolveNotebookAccesses(
        mockClient,
        permissions,
        'owner@example.com',
      );

      expect(result).toHaveLength(3);
      const types = result.map((a) => a.type);
      expect(types).toContain(ScopeAccessType.Read);
      expect(types).toContain(ScopeAccessType.Write);
      expect(types).toContain(ScopeAccessType.Manage);
    });

    it('resolves group permissions by expanding members', async () => {
      const permissions: DrivePermission[] = [
        {
          id: 'perm-group',
          roles: ['read'],
          grantedToV2: { group: { id: 'group-1', displayName: 'Team A' } },
        },
      ];

      (mockGraphService.getGroupMembers as ReturnType<typeof vi.fn>).mockResolvedValue([
        { id: 'member-1', mail: 'member1@example.com', displayName: 'Member 1' },
        { id: 'member-2', mail: 'member2@example.com', displayName: 'Member 2' },
      ]);

      mockUserService.findUserByEmail
        .mockResolvedValueOnce({ id: 'unique-m1' })
        .mockResolvedValueOnce({ id: 'unique-m2' });

      const result = await service.resolveNotebookAccesses(mockClient, permissions);

      expect(result).toHaveLength(2);
      expect(result[0]?.entityId).toBe('unique-m1');
      expect(result[1]?.entityId).toBe('unique-m2');
      expect(mockGraphService.getGroupMembers).toHaveBeenCalledWith(mockClient, 'group-1');
    });

    it('deduplicates users appearing in multiple permissions', async () => {
      const permissions: DrivePermission[] = [
        {
          id: 'perm-1',
          roles: ['read'],
          grantedToV2: { user: { email: 'user@example.com' } },
        },
        {
          id: 'perm-2',
          roles: ['write'],
          grantedToV2: { user: { email: 'user@example.com' } },
        },
      ];

      mockUserService.findUserByEmail.mockResolvedValue({ id: 'unique-user-1' });

      const result = await service.resolveNotebookAccesses(mockClient, permissions);

      expect(result).toHaveLength(1);
    });

    it('skips users not found in Unique', async () => {
      const permissions: DrivePermission[] = [
        {
          id: 'perm-1',
          roles: ['read'],
          grantedToV2: { user: { email: 'unknown@example.com' } },
        },
      ];

      mockUserService.findUserByEmail.mockResolvedValue(null);

      const result = await service.resolveNotebookAccesses(mockClient, permissions);

      expect(result).toHaveLength(0);
    });

    it('handles grantedToIdentitiesV2 permissions', async () => {
      const permissions: DrivePermission[] = [
        {
          id: 'perm-link',
          roles: ['read'],
          grantedToIdentitiesV2: [
            { user: { email: 'shared1@example.com' } },
            { user: { email: 'shared2@example.com' } },
          ],
        },
      ];

      mockUserService.findUserByEmail
        .mockResolvedValueOnce({ id: 'unique-s1' })
        .mockResolvedValueOnce({ id: 'unique-s2' });

      const result = await service.resolveNotebookAccesses(mockClient, permissions);

      expect(result).toHaveLength(2);
    });
  });
});
