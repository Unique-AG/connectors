import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { AppConfig, appConfig } from '~/config';
import {
  getRootScopeExternalId,
  getRootScopeExternalIdForUser,
  getRootScopePath,
  getRootScopePathForUser,
} from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { traceAttrs } from '../tracing.utils';

@Injectable()
export class CreateRootScopeCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
  ) {}

  @Span()
  public async run({
    userProviderUserId,
    userEmail,
  }: {
    userProviderUserId: string;
    userEmail: string | null;
  }): Promise<void> {
    traceAttrs({ userProviderUserId: userProviderUserId });
    const { id: parentScopeId } = await this.createScopeOnPath({
      scopePath: getRootScopePath(),
      externalId: getRootScopeExternalId(),
      // This is a total hack until we fix this in the monorepo because they do not check permissions correctly for integrations
      xUserRoles: ['chat.admin.all'],
    });
    const { id: userScopeId, created: userScopeCreated } = await this.createScopeOnPath({
      scopePath: getRootScopePathForUser(userProviderUserId),
      externalId: getRootScopeExternalIdForUser(userProviderUserId),
    });

    if (this.config.addScopePermissionsToUniqueUsers && userScopeCreated) {
      await this.addPermissionsForUser([parentScopeId, userScopeId], userEmail);
    }
  }

  private async addPermissionsForUser(scopeIds: string[], userEmail: string | null): Promise<void> {
    if (!userEmail) {
      this.logger.warn('Cannot add scope permissions: user email is not available');
      return;
    }

    const users = await this.uniqueApi.users.listAll();
    const uniqueUser = users.find((u) => u.email === userEmail);
    if (!uniqueUser) {
      this.logger.warn(
        `Cannot add scope permissions: no Unique user found with email ${userEmail}`,
      );
      return;
    }

    this.logger.debug(
      `Adding MANAGE scope permissions for user ${userEmail} on scopes ${scopeIds.join(', ')}`,
    );
    await Promise.all(
      scopeIds.map((scopeId) =>
        this.uniqueApi.scopes.createAccesses(scopeId, [
          { type: 'MANAGE', entityId: uniqueUser.id, entityType: 'USER' },
        ]),
      ),
    );
  }

  private async createScopeOnPath({
    scopePath,
    externalId,
    xUserRoles,
  }: {
    scopePath: string;
    externalId: string;
    xUserRoles?: string[];
  }): Promise<{ id: string; created: boolean }> {
    const scopeExists = await this.uniqueApi.scopes.getByExternalId(externalId);
    if (scopeExists) {
      this.logger.debug(`Scope: ${scopePath} already exists.`);
      return { id: scopeExists.id, created: false };
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
    return { id: scope.id, created: true };
  }
}
