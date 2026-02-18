import { Logger } from '@nestjs/common';
import { pick } from 'remeda';
import type { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import type { UniqueApiUsers } from '../types';
import {
  GET_CURRENT_USER_QUERY,
  type GetCurrentUserQueryResult,
  LIST_USERS_QUERY,
  type ListUsersQueryInput,
  type ListUsersQueryResult,
} from './users.queries';
import type { SimpleUser } from './users.types';

export class UsersService implements UniqueApiUsers {
  public constructor(
    private readonly scopeManagementClient: UniqueGraphqlClient,
    private readonly logger: Logger,
    private readonly options: { defaultBatchSize: number },
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
        take: this.options.defaultBatchSize,
        where: {
          active: {
            equals: true,
          },
        },
      });
      users.push(...batchResult.listUsers.nodes.map(pick(['id', 'email'])));
      batchCount = batchResult.listUsers.nodes.length;
      skip += this.options.defaultBatchSize;
    } while (batchCount === this.options.defaultBatchSize);

    return users;
  }

  public async getCurrentId(): Promise<string> {
    this.logger.log('Requesting current user ID from Unique API');

    const result =
      await this.scopeManagementClient.request<GetCurrentUserQueryResult>(GET_CURRENT_USER_QUERY);

    return result.me.user.id;
  }
}
