import { Logger } from '@nestjs/common';
import { pick } from 'remeda';
import type { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import { UniqueUsersFacade } from './unique-users.facade';
import {
  GET_CURRENT_USER_QUERY,
  type GetCurrentUserQueryResult,
  LIST_USERS_QUERY,
  type ListUsersQueryInput,
  type ListUsersQueryResult,
} from './users.queries';
import type { SimpleUser } from './users.types';

const BATCH_SIZE = 100;

export class UsersService implements UniqueUsersFacade {
  public constructor(
    private readonly scopeManagementClient: UniqueGraphqlClient,
    private readonly logger: Logger,
  ) {}

  public async listAll(): Promise<SimpleUser[]> {
    this.logger.log('Requesting all users from Unique API');

    let skip = 0;
    const users: SimpleUser[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.scopeManagementClient.request<
        ListUsersQueryResult,
        ListUsersQueryInput
      >(LIST_USERS_QUERY, {
        skip,
        take: BATCH_SIZE,
        where: {
          active: {
            equals: true,
          },
        },
      });
      users.push(...batchResult.listUsers.nodes.map(pick(['id', 'email'])));
      batchCount = batchResult.listUsers.nodes.length;
      skip += BATCH_SIZE;
    } while (batchCount === BATCH_SIZE);

    return users;
  }

  public async getCurrentId(): Promise<string> {
    this.logger.log('Requesting current user ID from Unique API');

    const result =
      await this.scopeManagementClient.request<GetCurrentUserQueryResult>(GET_CURRENT_USER_QUERY);

    return result.me.user.id;
  }
}
