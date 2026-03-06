import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable, Logger } from '@nestjs/common';
import {
  getRootScopeExternalId,
  getRootScopeExternalIdForUser,
  getRootScopePath,
  getRootScopePathForUser,
} from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { Span } from 'nestjs-otel';
import { traceAttrs } from '../tracing.utils';

@Injectable()
export class CreateRootScopeCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@InjectUniqueApi() private readonly uniqueApi: UniqueApiClient) {}

  @Span()
  public async run({ userProviderUserId }: { userProviderUserId: string }): Promise<void> {
    traceAttrs({ userProviderUserId: userProviderUserId });
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
    const scopeExists = await this.uniqueApi.scopes.getByExternalId(externalId);
    if (scopeExists) {
      this.logger.debug(`Scope: ${scopePath} already exists.`);
      return;
    }

    this.logger.debug(`Create Scope: ${scopePath}`);
    const [scope] = await this.uniqueApi.scopes.createFromPaths([scopePath], {
      includePermissions: true,
      inheritAccess: true,
      xUserRoles,
    });
    assert.ok(scope, `Could not create scope on path: ${scopePath}`);
    if (scope.externalId !== externalId) {
      this.logger.debug(`Update scope with external id: ${scopePath}`);
      await this.uniqueApi.scopes.updateExternalId(scope.id, externalId);
    }
  }
}
