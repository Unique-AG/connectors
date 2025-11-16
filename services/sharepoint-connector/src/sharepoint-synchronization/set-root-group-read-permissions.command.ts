import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import { UniqueGroupsService } from '../unique-api/unique-groups/unique-groups.service';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { ScopeAccess } from '../unique-api/unique-scopes/unique-scopes.types';

@Injectable()
export class SetRootGroupReadPermissionsCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueGroupsService: UniqueGroupsService,
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  // Sets general permissions for the first several levels of folders that do not have permissions
  // fetched from SharePoint. These are simply folders accesses so everyone can see them, even if
  // they are empty to them due to lack of permissions.
  public async run(): Promise<void> {
    this.logger.log('Starting root group read permissions setup');

    const rootGroup = await this.uniqueGroupsService.getRootGroup();
    if (!rootGroup) {
      this.logger.warn('Root group not found, skipping root group permission setup');
      return;
    }

    this.logger.debug(`Found root group: ${rootGroup.name} (${rootGroup.id})`);

    const rootGroupAccess: ScopeAccess[] = [
      {
        type: 'READ' as const,
        entityId: rootGroup.id,
        entityType: 'GROUP' as const,
      },
    ];

    // TODO: It will most probably need to be adjusted when we decide on how exactly set inconfig
    //       root scope. It should be single config for that, regardless of mode but right now here
    //       we handle two configs for that.
    const ingestionMode = this.configService.get('unique.ingestionMode', { infer: true });
    if (ingestionMode === IngestionMode.Recursive) {
      await this.setRootGroupPermissionsRecursiveMode(rootGroupAccess);
    } else {
      await this.setRootGroupPermissionsFlatMode(rootGroupAccess);
    }
  }

  private async setRootGroupPermissionsRecursiveMode(
    rootGroupAccess: ScopeAccess[],
  ): Promise<void> {
    this.logger.log('Processing root group permissions in recursive mode');

    const rootScopeName = this.configService.get('unique.rootScopeName', {
      infer: true,
    });
    assert.ok(rootScopeName, 'rootScopeName must be configured for recursive mode');

    const rootScope = await this.uniqueScopesService.getRootScopeByName(rootScopeName);
    if (!rootScope) {
      this.logger.warn(
        `Root scope "${rootScopeName}" not found, skipping root group permission setup`,
      );
      return;
    }

    this.logger.debug(`Found root scope: ${rootScope.name} (${rootScope.id})`);

    const siteScopes = await this.uniqueScopesService.listChildrenScopes(rootScope.id);
    this.logger.log(`Found ${siteScopes.length} site scope(s) under root scope`);

    // We do two levels of root group permissions setup because these levels are not an actual
    // directories yet.
    // First level is the root scope itself, selected by user in config.
    // Second level are the sites selected by user in the config.
    // Third level are the drives in the site + SitePages list with aspx pages.
    // Examples: /RootScope/Site/Drive1, /RootScope/Site/SitePages
    let totalScopesProcessed = 0;
    for (const siteScope of siteScopes) {
      this.logger.debug(
        `Setting root group permissions on site scope: ${siteScope.name} (${siteScope.id})`,
      );
      await this.uniqueScopesService.createScopeAccesses(siteScope.id, rootGroupAccess);
      totalScopesProcessed++;

      const childScopes = await this.uniqueScopesService.listChildrenScopes(siteScope.id);
      this.logger.debug(
        `Found ${childScopes.length} child scope(s) under site scope: ${siteScope.name}`,
      );
      for (const childScope of childScopes) {
        this.logger.debug(
          `Setting root group permissions on child scope: ${childScope.name} (${childScope.id})`,
        );
        await this.uniqueScopesService.createScopeAccesses(childScope.id, rootGroupAccess);
        totalScopesProcessed++;
      }
    }

    this.logger.log(
      `Completed root group permissions setup in recursive mode: processed ${totalScopesProcessed} scope(s)`,
    );
  }

  private async setRootGroupPermissionsFlatMode(rootGroupAccess: ScopeAccess[]): Promise<void> {
    this.logger.log('Processing root group permissions in flat mode');

    const scopeId = this.configService.get('unique.scopeId', { infer: true });
    assert.ok(scopeId, 'scopeId must be configured for flat mode');

    this.logger.debug(`Setting root group permissions on scope: ${scopeId}`);
    await this.uniqueScopesService.createScopeAccesses(scopeId, rootGroupAccess);

    this.logger.log('Completed root group permissions setup in flat mode');
  }
}
