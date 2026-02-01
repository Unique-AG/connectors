import { Inject, Injectable, Logger } from '@nestjs/common';
import { isNullish } from 'remeda';
import { BatchProcessorService } from '../../shared/services/batch-processor.service';
import { SCOPE_MANAGEMENT_CLIENT, UniqueGraphqlClient } from '../clients/unique-graphql.client';
import {
  CREATE_SCOPE_ACCESSES_MUTATION,
  CreateScopeAccessesMutationInput,
  CreateScopeAccessesMutationResult,
  DELETE_FOLDER_MUTATION,
  DELETE_SCOPE_ACCESSES_MUTATION,
  DeleteFolderMutationInput,
  DeleteFolderMutationResult,
  DeleteScopeAccessesMutationInput,
  DeleteScopeAccessesMutationResult,
  GenerateScopesBasedOnPathsMutationInput,
  GenerateScopesBasedOnPathsMutationResult,
  getGenerateScopesBasedOnPathsMutation,
  PAGINATED_SCOPE_QUERY,
  PaginatedScopeQueryInput,
  PaginatedScopeQueryResult,
  UPDATE_SCOPE_MUTATION,
  UpdateScopeMutationInput,
  UpdateScopeMutationResult,
} from './unique-scopes.consts';
import { Scope, ScopeAccess } from './unique-scopes.types';

const BATCH_SIZE = 100;

@Injectable()
export class UniqueScopesService {
  private readonly logger = new Logger(this.constructor.name);
  public constructor(
    @Inject(SCOPE_MANAGEMENT_CLIENT) private readonly scopeManagementClient: UniqueGraphqlClient,
    private readonly batchProcessor: BatchProcessorService,
  ) {}

  public async createScopesBasedOnPaths(
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

    const allScopes = await this.batchProcessor.processInBatches({
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
      logPrefix: '[createScopesBasedOnPaths]',
    });

    this.logger.debug(`Created ${allScopes.length} scopes from ${paths.length} paths`);
    return allScopes;
  }

  public async updateScopeExternalId(
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

  public async updateScopeParent(
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

  public async createScopeAccesses(
    scopeId: string,
    scopeAccesses: ScopeAccess[],
    applyToSubScopes: boolean = false,
  ): Promise<void> {
    this.logger.debug(
      `Creating ${scopeAccesses.length} scope accesses for scope ${scopeId} (applyToSubScopes: ${applyToSubScopes})`,
    );

    await this.scopeManagementClient.request<
      CreateScopeAccessesMutationResult,
      CreateScopeAccessesMutationInput
    >(CREATE_SCOPE_ACCESSES_MUTATION, {
      scopeId,
      scopeAccesses: scopeAccesses.map((scopeAccess) => ({
        accessType: scopeAccess.type,
        entityId: scopeAccess.entityId,
        entityType: scopeAccess.entityType,
      })),
      applyToSubScopes,
      skipFileAccessPropagation: true,
    });
  }

  public async deleteScopeAccesses(
    scopeId: string,
    scopeAccesses: ScopeAccess[],
    applyToSubScopes: boolean = false,
  ): Promise<void> {
    this.logger.debug(
      `Deleting ${scopeAccesses.length} scope accesses for scope ${scopeId} (applyToSubScopes: ${applyToSubScopes})`,
    );

    await this.scopeManagementClient.request<
      DeleteScopeAccessesMutationResult,
      DeleteScopeAccessesMutationInput
    >(DELETE_SCOPE_ACCESSES_MUTATION, {
      scopeId,
      scopeAccesses: scopeAccesses.map((scopeAccess) => ({
        accessType: scopeAccess.type,
        entityId: scopeAccess.entityId,
        entityType: scopeAccess.entityType,
      })),
      applyToSubScopes,
      skipFileAccessPropagation: true,
    });
  }

  public async getScopeById(id: string): Promise<Scope | null> {
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

  public async getScopeByExternalId(externalId: string): Promise<Scope | null> {
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

  public async listChildrenScopes(parentId: string): Promise<Scope[]> {
    const logPrefix = `[ParentId: ${parentId}]`;
    this.logger.debug(`${logPrefix} Fetching children scopes from Unique API`);

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

  public async deleteScopeRecursively(
    scopeId: string,
  ): Promise<DeleteFolderMutationResult['deleteFolder']> {
    this.logger.debug(`Deleting scope recursively: ${scopeId}`);

    const result = await this.scopeManagementClient.request<
      DeleteFolderMutationResult,
      DeleteFolderMutationInput
    >(DELETE_FOLDER_MUTATION, {
      scopeId,
      recursive: true,
    });

    this.logger.debug(
      `Deleted ${result.deleteFolder.successFolders.length} folders successfully, ${result.deleteFolder.failedFolders.length} failed`,
    );

    return result.deleteFolder;
  }
}
