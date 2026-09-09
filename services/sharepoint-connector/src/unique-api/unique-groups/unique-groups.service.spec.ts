import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { SCOPE_MANAGEMENT_CLIENT } from '../clients/unique-graphql.client';
import { UniqueGroupsService } from './unique-groups.service';

describe('UniqueGroupsService', () => {
  let service: UniqueGroupsService;
  let request: Mock;

  beforeEach(async () => {
    request = vi.fn().mockResolvedValue({ addGroupMembers: [] });

    const { unit } = await TestBed.solitary(UniqueGroupsService)
      .mock(SCOPE_MANAGEMENT_CLIENT)
      .impl(() => ({ request }))
      .compile();
    service = unit;
  });

  describe('addGroupMembers', () => {
    it('sends members in a single request when at most 100 ids are provided', async () => {
      const memberIds = Array.from({ length: 100 }, (_, index) => `user-${index}`);

      await service.addGroupMembers('group-1', memberIds);

      expect(request).toHaveBeenCalledOnce();
      expect(request).toHaveBeenCalledWith(
        expect.any(String),
        { groupId: 'group-1', userIds: memberIds },
        expect.objectContaining({ logSafeKeys: expect.any(Array) }),
      );
    });

    it('chunks members into batches of 100', async () => {
      const memberIds = Array.from({ length: 250 }, (_, index) => `user-${index}`);

      await service.addGroupMembers('group-1', memberIds);

      expect(request).toHaveBeenCalledTimes(3);
      expect(request.mock.calls[0]?.[1]).toEqual({
        groupId: 'group-1',
        userIds: memberIds.slice(0, 100),
      });
      expect(request.mock.calls[1]?.[1]).toEqual({
        groupId: 'group-1',
        userIds: memberIds.slice(100, 200),
      });
      expect(request.mock.calls[2]?.[1]).toEqual({
        groupId: 'group-1',
        userIds: memberIds.slice(200),
      });
    });
  });
});
