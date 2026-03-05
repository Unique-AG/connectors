import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import {
  getRootScopeExternalId,
  getRootScopeExternalIdForUser,
  getRootScopePath,
  getRootScopePathForUser,
} from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';

@Injectable()
export class CreateRootScopeCommand {
  public constructor(@InjectUniqueApi() private readonly uniqueApi: UniqueApiClient) {}

  public async run({
    userProviderUserId,
  }: {
    userProviderUserId: string;
    userProfileEmail: string;
  }): Promise<void> {
    await this.createScopeOnPath({
      scopePath: getRootScopePath(),
      externalId: getRootScopeExternalId(),
      // This is a total hack until we fix this in the monorepo because they do not check permissions correctly for integrations
      xUserRoles: ['chat.admin.all'],
    });
    await this.createScopeOnPath({
      scopePath: getRootScopePathForUser(userProviderUserId),
      externalId: getRootScopeExternalIdForUser(userProviderUserId),
    });
  }

  private async createScopeOnPath({
    scopePath,
    externalId,
    xUserRoles,
  }: {
    scopePath: string;
    externalId: string;
    xUserRoles?: string[];
  }): Promise<void> {
    // const rootScopePartForUser = getRootScopeExternalIdForUser(userProviderUserId);
    const scopeExists = await this.uniqueApi.scopes.getByExternalId(externalId);
    if (scopeExists) {
      return;
    }

    const [scope] = await this.uniqueApi.scopes.createFromPaths([scopePath], {
      includePermissions: true,
      inheritAccess: true,
      xUserRoles,
    });
    assert.ok(scope, `Could not create scope on path: ${scopePath}`);
    if (scope.externalId !== externalId) {
      await this.uniqueApi.scopes.updateExternalId(scope.id, externalId);
    }
  }
}
