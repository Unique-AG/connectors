import { Injectable, Logger } from '@nestjs/common';
import { pick } from 'remeda';
import { ScopeManagementClient } from '../clients/scope-management.client';
import { LIST_USERS_QUERY, ListUsersQueryInput, ListUsersQueryResult } from './unique-users.consts';
import { SimpleUniqueUser } from './unique-users.types';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueUsersService {
  private readonly logger = new Logger(this.constructor.name);
  public constructor(private readonly scopeManagementClient: ScopeManagementClient) {}

  public async listAllUsers(): Promise<SimpleUniqueUser[]> {
    this.logger.log('Requesting all users from Unique API');

    let skip = 0;
    const users: SimpleUniqueUser[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.scopeManagementClient.get(
        async (client) =>
          await client.request<ListUsersQueryResult, ListUsersQueryInput>(LIST_USERS_QUERY, {
            skip,
            take: BATCH_SIZE,
          }),
      );
      users.push(...batchResult.listUsers.nodes.map(pick(['id', 'email'])));
      batchCount = batchResult.listUsers.nodes.length;
      skip += BATCH_SIZE;
    } while (batchCount === BATCH_SIZE);

    return users;
  }
}
