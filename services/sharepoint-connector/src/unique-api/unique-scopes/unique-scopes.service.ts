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
} from './unique-scopes.consts';
import { Scope, ScopeAccess } from './unique-scopes.types';

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
    this.logger.log(`Creating scopes based on ${paths.length} paths`);

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
    this.logger.log(
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
          },
        ),
    );
  }

  public async deleteScopeAccesses(
    scopeId: string,
    scopeAccesses: ScopeAccess[],
    applyToSubScopes: boolean = false,
  ): Promise<void> {
    this.logger.log(
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
          },
        ),
    );
  }
}
