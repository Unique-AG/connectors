import { isNullish } from 'remeda';
import type { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import { processInBatches } from '../core/batch-processor.service';
import {
  CREATE_SCOPE_ACCESSES_MUTATION,
  type CreateScopeAccessesMutationInput,
  type CreateScopeAccessesMutationResult,
  DELETE_FOLDER_MUTATION,
  DELETE_SCOPE_ACCESSES_MUTATION,
  type DeleteFolderMutationInput,
  type DeleteFolderMutationResult,
  type DeleteScopeAccessesMutationInput,
  type DeleteScopeAccessesMutationResult,
  type GenerateScopesBasedOnPathsMutationInput,
  type GenerateScopesBasedOnPathsMutationResult,
  getGenerateScopesBasedOnPathsMutation,
  PAGINATED_SCOPE_QUERY,
  type PaginatedScopeQueryInput,
  type PaginatedScopeQueryResult,
  UPDATE_SCOPE_MUTATION,
  type UpdateScopeMutationInput,
  type UpdateScopeMutationResult,
} from './scopes.queries';
import type { Scope, ScopeAccess } from './scopes.types';

const BATCH_SIZE = 100;

interface ScopesServiceDeps {
  scopeManagementClient: UniqueGraphqlClient;
  logger: { debug: (msg: string) => void; error: (obj: object) => void };
}

export class ScopesService {
  private readonly scopeManagementClient: UniqueGraphqlClient;
  private readonly logger: ScopesServiceDeps['logger'];

  public constructor(deps: ScopesServiceDeps) {
    this.scopeManagementClient = deps.scopeManagementClient;
    this.logger = deps.logger;
  }

  public async createFromPaths(
    paths: string[],
    opts: { includePermissions: boolean; inheritAccess: boolean } = {
      includePermissions: false,
      inheritAccess: true,
    },
  ): Promise<Scope[]> {
    this.logger.debug(`Creating scopes based on ${paths.length} paths`);

    if (paths.length === 0) {
      return [];
    }

    const mutation = getGenerateScopesBasedOnPathsMutation(opts.includePermissions);

    const allScopes = await processInBatches({
      items: paths,
      batchSize: BATCH_SIZE,
      processor: async (batch) => {
        const variables: GenerateScopesBasedOnPathsMutationInput = { paths: batch };

        if (!isNullish(opts.inheritAccess)) {
          variables.inheritAccess = opts.inheritAccess;
        }

        const result = await this.scopeManagementClient.request<
          GenerateScopesBasedOnPathsMutationResult,
          GenerateScopesBasedOnPathsMutationInput
        >(mutation, variables);

        return result.generateScopesBasedOnPaths;
      },
      logger: this.logger,
      logPrefix: '[createFromPaths]',
    });

    this.logger.debug(`Created ${allScopes.length} scopes from ${paths.length} paths`);
    return allScopes;
  }

  public async getById(id: string): Promise<Scope | null> {
    const result = await this.scopeManagementClient.request<
      PaginatedScopeQueryResult,
      PaginatedScopeQueryInput
    >(PAGINATED_SCOPE_QUERY, {
      skip: 0,
      take: 1,
      where: {
        id: { equals: id },
      },
    });

    return result.paginatedScope.nodes[0] ?? null;
  }

  public async getByExternalId(externalId: string): Promise<Scope | null> {
    const result = await this.scopeManagementClient.request<
      PaginatedScopeQueryResult,
      PaginatedScopeQueryInput
    >(PAGINATED_SCOPE_QUERY, {
      skip: 0,
      take: 1,
      where: {
        externalId: { equals: externalId },
      },
    });

    return result.paginatedScope.nodes[0] ?? null;
  }

  public async updateExternalId(
    scopeId: string,
    externalId: string,
  ): Promise<{ id: string; externalId: string | null }> {
    const result = await this.scopeManagementClient.request<
      UpdateScopeMutationResult,
      UpdateScopeMutationInput
    >(UPDATE_SCOPE_MUTATION, {
      id: scopeId,
      input: { externalId },
    });

    return result.updateScope;
  }

  public async updateParent(
    scopeId: string,
    newParentId: string,
  ): Promise<{ id: string; parentId: string | null }> {
    const result = await this.scopeManagementClient.request<
      UpdateScopeMutationResult,
      UpdateScopeMutationInput
    >(UPDATE_SCOPE_MUTATION, {
      id: scopeId,
      input: {
        parrentScope: {
          connect: { id: newParentId },
        },
      },
    });

    return result.updateScope;
  }

  public async listChildren(parentId: string): Promise<Scope[]> {
    const logPrefix = `[ParentId: ${parentId}]`;
    this.logger.debug(`${logPrefix} Fetching children scopes`);

    let skip = 0;
    const scopes: Scope[] = [];

    let batchCount = 0;
    do {
      const batchResult = await this.scopeManagementClient.request<
        PaginatedScopeQueryResult,
        PaginatedScopeQueryInput
      >(PAGINATED_SCOPE_QUERY, {
        skip,
        take: BATCH_SIZE,
        where: {
          parentId: {
            equals: parentId,
          },
        },
      });
      scopes.push(...batchResult.paginatedScope.nodes);
      batchCount = batchResult.paginatedScope.nodes.length;
      skip += BATCH_SIZE;
    } while (batchCount === BATCH_SIZE);

    return scopes;
  }

  public async createAccesses(
    scopeId: string,
    accesses: ScopeAccess[],
    applyToSubScopes = false,
  ): Promise<void> {
    this.logger.debug(
      `Creating ${accesses.length} scope accesses for scope ${scopeId} (applyToSubScopes: ${applyToSubScopes})`,
    );

    await this.scopeManagementClient.request<
      CreateScopeAccessesMutationResult,
      CreateScopeAccessesMutationInput
    >(CREATE_SCOPE_ACCESSES_MUTATION, {
      scopeId,
      scopeAccesses: accesses.map((access) => ({
        accessType: access.type,
        entityId: access.entityId,
        entityType: access.entityType,
      })),
      applyToSubScopes,
      skipFileAccessPropagation: true,
    });
  }

  public async deleteAccesses(
    scopeId: string,
    accesses: ScopeAccess[],
    applyToSubScopes = false,
  ): Promise<void> {
    this.logger.debug(
      `Deleting ${accesses.length} scope accesses for scope ${scopeId} (applyToSubScopes: ${applyToSubScopes})`,
    );

    await this.scopeManagementClient.request<
      DeleteScopeAccessesMutationResult,
      DeleteScopeAccessesMutationInput
    >(DELETE_SCOPE_ACCESSES_MUTATION, {
      scopeId,
      scopeAccesses: accesses.map((access) => ({
        accessType: access.type,
        entityId: access.entityId,
        entityType: access.entityType,
      })),
      applyToSubScopes,
      skipFileAccessPropagation: true,
    });
  }

  public async delete(
    scopeId: string,
    options: { recursive?: boolean } = {},
  ): Promise<DeleteFolderMutationResult['deleteFolder']> {
    const { recursive = false } = options;
    this.logger.debug(`Deleting scope: ${scopeId} (recursive: ${recursive})`);

    const result = await this.scopeManagementClient.request<
      DeleteFolderMutationResult,
      DeleteFolderMutationInput
    >(DELETE_FOLDER_MUTATION, {
      scopeId,
      recursive,
    });

    this.logger.debug(
      `Deleted ${result.deleteFolder.successFolders.length} folders successfully, ${result.deleteFolder.failedFolders.length} failed`,
    );

    return result.deleteFolder;
  }
}
