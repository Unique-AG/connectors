import { Injectable, Logger } from '@nestjs/common';
import { ScopeManagementClient } from '../clients/scope-management.client';
import {
  GenerateScopesBasedOnPathsMutationInput,
  GenerateScopesBasedOnPathsMutationResult,
  getGenerateScopesBasedOnPathsMutation,
} from './unique-scopes.consts';
import { Scope } from './unique-scopes.types';

@Injectable()
export class UniqueScopesService {
  private readonly logger = new Logger(this.constructor.name);
  public constructor(private readonly scopeManagementClient: ScopeManagementClient) {}

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
}
