import { Logger } from '@nestjs/common';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UniqueGraphqlClient } from '../../clients/unique-graphql.client';
import { LIST_USERS_QUERY } from '../users.queries';
import { UsersService } from '../users.service';

function createMockGraphqlClient(): UniqueGraphqlClient {
  return {
    request: vi.fn(),
    close: vi.fn(),
  } as unknown as UniqueGraphqlClient;
}

describe('UsersService', () => {
  let service: UsersService;
  let graphqlClient: UniqueGraphqlClient;

  beforeEach(() => {
    graphqlClient = createMockGraphqlClient();
    service = new UsersService(graphqlClient, new Logger('TestUsersService'));
  });

  describe('findByEmail', () => {
    it('returns the first matching user with companyId', async () => {
      vi.mocked(graphqlClient.request).mockResolvedValue({
        listUsers: {
          totalCount: 1,
          nodes: [{ id: 'user-123', email: 'john@example.com', companyId: 'comp-456', active: true }],
        },
      });

      const result = await service.findByEmail('john@example.com');

      expect(result).toEqual({ id: 'user-123', email: 'john@example.com', companyId: 'comp-456' });
      expect(graphqlClient.request).toHaveBeenCalledWith(LIST_USERS_QUERY, {
        skip: 0,
        take: 1,
        where: { email: { equals: 'john@example.com' } },
      });
    });

    it('returns null when no users match', async () => {
      vi.mocked(graphqlClient.request).mockResolvedValue({
        listUsers: { totalCount: 0, nodes: [] },
      });

      const result = await service.findByEmail('nobody@example.com');

      expect(result).toBeNull();
    });
  });
});
