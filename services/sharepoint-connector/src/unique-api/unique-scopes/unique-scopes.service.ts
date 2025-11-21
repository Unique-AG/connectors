import { Inject, Injectable, Logger } from '@nestjs/common';
import { SCOPE_MANAGEMENT_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
import {
  CREATE_SCOPE_ACCESSES_MUTATION,
  CreateScopeAccessesMutationInput,
  CreateScopeAccessesMutationResult,
  DELETE_SCOPE_ACCESSES_MUTATION,
  DeleteScopeAccessesMutationInput,
  DeleteScopeAccessesMutationResult,
  GenerateScopesBasedOnPathsMutationInput,
  GenerateScopesBasedOnPathsMutationResult,
  getGenerateScopesBasedOnPathsMutation,
  PAGINATED_SCOPE_QUERY,
  PaginatedScopeQueryInput,
  PaginatedScopeQueryResult,
} from './unique-scopes.consts';
import { Scope, ScopeAccess } from './unique-scopes.types';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueScopesService {
  private readonly logger = new Logger(this.constructor.name);
  public constructor(
    @Inject(SCOPE_MANAGEMENT_CLIENT) private readonly scopeManagementClient: UniqueGraphqlClient,
  ) {}

  public async createScopesBasedOnPaths(
    paths: string[],
    opts: { includePermissions: boolean } = { includePermissions: false },
  ): Promise<Scope[]> {
    this.logger.debug(`Creating scopes based on ${paths.length} paths`);

    const mutation = getGenerateScopesBasedOnPathsMutation(opts.includePermissions);

    const result = await this.scopeManagementClient.get(
      async (client) =>
        await client.request<
          GenerateScopesBasedOnPathsMutationResult,
          GenerateScopesBasedOnPathsMutationInput
        >(mutation, { paths }),
    );

    return result.generateScopesBasedOnPaths;
  }

  public async createScopeAccesses(
    scopeId: string,
    scopeAccesses: ScopeAccess[],
    applyToSubScopes: boolean = false,
  ): Promise<void> {
    this.logger.debug(
      `Creating ${scopeAccesses.length} scope accesses for scope ${scopeId} (applyToSubScopes: ${applyToSubScopes})`,
    );

    await this.scopeManagementClient.get(
      async (client) =>
        await client.request<CreateScopeAccessesMutationResult, CreateScopeAccessesMutationInput>(
          CREATE_SCOPE_ACCESSES_MUTATION,
          {
            scopeId,
            scopeAccesses: scopeAccesses.map((scopeAccess) => ({
              accessType: scopeAccess.type,
              entityId: scopeAccess.entityId,
              entityType: scopeAccess.entityType,
            })),
            applyToSubScopes,
            skipFileAccessPropagation: true,
          },
        ),
    );
  }

  public async deleteScopeAccesses(
    scopeId: string,
    scopeAccesses: ScopeAccess[],
    applyToSubScopes: boolean = false,
  ): Promise<void> {
    this.logger.debug(
      `Deleting ${scopeAccesses.length} scope accesses for scope ${scopeId} (applyToSubScopes: ${applyToSubScopes})`,
    );

    await this.scopeManagementClient.get(
      async (client) =>
        await client.request<DeleteScopeAccessesMutationResult, DeleteScopeAccessesMutationInput>(
          DELETE_SCOPE_ACCESSES_MUTATION,
          {
            scopeId,
            scopeAccesses: scopeAccesses.map((scopeAccess) => ({
              accessType: scopeAccess.type,
              entityId: scopeAccess.entityId,
              entityType: scopeAccess.entityType,
            })),
            applyToSubScopes,
            skipFileAccessPropagation: true,
          },
        ),
    );
  }

  // TODO: Remove this method once we refer to root scope by its ID in the config.
  // Getting the root scope this way is temporary. This wil break if we will have deeper paths for
  // the root ingestion scope. We plan to refer to root scope by its ID in the config. Once we do
  // that, we can remove this method. If we decide to refer to root scope by path, we have to double
  // check how this method should work.
  public async getRootScopeByName(name: string): Promise<Scope | null> {
    const result = await this.scopeManagementClient.get(
      async (client) =>
        await client.request<PaginatedScopeQueryResult, PaginatedScopeQueryInput>(
          PAGINATED_SCOPE_QUERY,
          {
            skip: 0,
            take: 1,
            where: {
              name: { equals: name },
              parentId: null,
            },
          },
        ),
    );

    return result.paginatedScope.nodes[0] ?? null;
  }

  public async listChildrenScopes(parentId: string): Promise<Scope[]> {
    this.logger.debug(`Fetching children scopes for parent ${parentId} from Unique API`);

    let skip = 0;
    const scopes: Scope[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.scopeManagementClient.get(
        async (client) =>
          await client.request<PaginatedScopeQueryResult, PaginatedScopeQueryInput>(
            PAGINATED_SCOPE_QUERY,
            {
              skip,
              take: BATCH_SIZE,
              where: {
                parentId: {
                  equals: parentId,
                },
              },
            },
          ),
      );
      scopes.push(...batchResult.paginatedScope.nodes);
      batchCount = batchResult.paginatedScope.nodes.length;
      skip += BATCH_SIZE;
    } while (batchCount === BATCH_SIZE);

    return scopes;
  }
}
