import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { pick } from 'remeda';
import { Config } from '../../config';
import { SCOPE_MANAGEMENT_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
import {
  GET_CURRENT_USER_QUERY,
  GetCurrentUserQueryResult,
  LIST_USERS_QUERY,
  ListUsersQueryInput,
  ListUsersQueryResult,
} from './unique-users.consts';
import { SimpleUniqueUser } from './unique-users.types';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueUsersService {
  private readonly logger = new Logger(this.constructor.name);
  public constructor(
    @Inject(SCOPE_MANAGEMENT_CLIENT) private readonly scopeManagementClient: UniqueGraphqlClient,
    private readonly configService: ConfigService<Config, true>,
  ) {}

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

  public async getCurrentUserId(): Promise<string> {
    this.logger.log('Requesting current user ID from Unique API');

    const uniqueConfig = this.configService.get('unique', { infer: true });
    if (uniqueConfig.serviceAuthMode === 'cluster_local') {
      // This a hack that we added because we do not yet have permissions to access the me query in
      // cluster_local mode. We then provide info that we're a service but our service don't have
      // access yet. For external mode we use Zitadel authentication so we're treated as a user.
      //
      // We type cast the value of `x-user-id` because we know that it's a string and it's present
      // due to validation in unique.config.ts.
      return uniqueConfig.serviceExtraHeaders['x-user-id'] as string;
    }

    const result = await this.scopeManagementClient.get(
      async (client) => await client.request<GetCurrentUserQueryResult>(GET_CURRENT_USER_QUERY, {}),
    );

    return result.me.user.id;
  }
}
