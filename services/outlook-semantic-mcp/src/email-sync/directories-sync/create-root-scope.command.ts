import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { getRootScopeExternalId, getRootScopePath } from '~/unique/get-root-scope-path';
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
    const externalId = getRootScopeExternalId(userProviderUserId);
    const rootScopeExists = await this.uniqueApi.scopes.getByExternalId(externalId);
    if (rootScopeExists) {
      return;
    }

    const rootScopePath = getRootScopePath(userProviderUserId);
    const [rootScope] = await this.uniqueApi.scopes.createFromPaths([rootScopePath], {
      includePermissions: true,
      inheritAccess: true,
    });
    assert.ok(rootScope, `Parent scope id`);
    if (!rootScope.externalId) {
      await this.uniqueApi.scopes.updateExternalId(rootScope.id, externalId);
    }
  }
}
