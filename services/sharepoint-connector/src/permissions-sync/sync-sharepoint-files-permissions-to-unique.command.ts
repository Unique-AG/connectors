import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import {
  differenceWith,
  filter,
  isDeepEqual,
  isNonNullish,
  isNullish,
  map,
  partition,
  pipe,
} from 'remeda';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueFile, UniqueFileAccessInput } from '../unique-api/unique-files/unique-files.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { Membership, UniqueGroupsMap, UniqueUsersMap } from './types';
import { groupDistinctId } from './utils';

interface Input {
  siteId: string;
  sharePoint: {
    permissionsMap: Record<string, Membership[]>;
  };
  unique: {
    groupsMap: UniqueGroupsMap;
    usersMap: UniqueUsersMap;
  };
}

@Injectable()
export class SyncSharepointFilesPermissionsToUniqueCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly uniqueUsersService: UniqueUsersService,
  ) {}

  public async run(input: Input): Promise<void> {
    const { siteId, sharePoint, unique } = input;

    const logPrefix = `[Site: ${siteId}]`;
    this.logger.log(
      `${logPrefix} Starting permissions sync for ` +
        `${Object.keys(sharePoint.permissionsMap).length} items`,
    );

    this.logger.log(`${logPrefix} Fetching unique files`);
    const uniqueFiles = await this.uniqueFilesService.getFilesForSite(siteId);
    this.logger.log(`${logPrefix} Fetched ${uniqueFiles.length} unique files`);

    // We need current user id to be sure to not remove their access to file, because it won't be
    // present in SharePoint, but should be present in Unique.
    const currentUserId = await this.uniqueUsersService.getCurrentUserId();
    // Maps from scope id to permissions to add/remove, because API calls are limited to the scope
    const permissionsToAddByScopeId: Record<string, UniqueFileAccessInput[]> = {};
    const permissionsToRemoveByScopeId: Record<string, UniqueFileAccessInput[]> = {};
    for (const uniqueFile of uniqueFiles) {
      const loopLogPrefix = `${logPrefix}[File: ${uniqueFile.id}]`;
      this.logger.debug(`${loopLogPrefix} Starting permissions processing`);
      const permissions = sharePoint.permissionsMap[uniqueFile.key];

      if (isNullish(permissions)) {
        this.logger.warn(
          `${loopLogPrefix} No SharePoint permissions found for key ${uniqueFile.key}`,
        );
        continue;
      }

      const uniqueFileAccessInputsFromSharePoint =
        this.mapSharePointPermissionsToUniqueFileAccessInputs(
          uniqueFile.id,
          permissions,
          unique.groupsMap,
          unique.usersMap,
        );
      const uniqueFileAccessInputsFromUnique =
        this.extractUniqueFileAccessInputsFromUniqueFile(uniqueFile);

      const permissionsToAdd = differenceWith(
        uniqueFileAccessInputsFromSharePoint,
        uniqueFileAccessInputsFromUnique,
        isDeepEqual,
      );
      this.logger.debug(`${loopLogPrefix} ${permissionsToAdd.length} permissions to add`);
      if (permissionsToAdd.length > 0) {
        const currentScopePermissionsToAdd = permissionsToAddByScopeId[uniqueFile.ownerId] ?? [];
        permissionsToAddByScopeId[uniqueFile.ownerId] =
          currentScopePermissionsToAdd.concat(permissionsToAdd);
      }

      const permissionsToRemove = differenceWith(
        uniqueFileAccessInputsFromUnique,
        uniqueFileAccessInputsFromSharePoint,
        isDeepEqual,
      ).filter(
        ({ entityType, entityId }) => !(entityType === 'USER' && entityId === currentUserId),
      );
      this.logger.debug(`${loopLogPrefix} ${permissionsToRemove.length} permissions to remove`);
      if (permissionsToRemove.length > 0) {
        const currentScopePermissionsToRemove =
          permissionsToRemoveByScopeId[uniqueFile.ownerId] ?? [];
        permissionsToRemoveByScopeId[uniqueFile.ownerId] =
          currentScopePermissionsToRemove.concat(permissionsToRemove);
      }
    }

    this.logger.log(
      `${logPrefix} Adding permissions to unique files in ${Object.keys(permissionsToAddByScopeId).length} scopes`,
    );
    for (const [scopeId, permissionsToAdd] of Object.entries(permissionsToAddByScopeId)) {
      this.logger.debug(
        `${logPrefix}[Scope: ${scopeId}] Adding ${permissionsToAdd.length} permissions`,
      );
      await this.uniqueFilesService.addAccesses(scopeId, permissionsToAdd);
    }

    this.logger.log(
      `${logPrefix} Removing permissions from unique files in ${Object.keys(permissionsToRemoveByScopeId).length} scopes`,
    );
    for (const [scopeId, permissionsToRemove] of Object.entries(permissionsToRemoveByScopeId)) {
      this.logger.debug(
        `${logPrefix}[Scope: ${scopeId}] Removing ${permissionsToRemove.length} permissions`,
      );
      await this.uniqueFilesService.removeAccesses(scopeId, permissionsToRemove);
    }
  }

  private extractUniqueFileAccessInputsFromUniqueFile(
    uniqueFile: UniqueFile,
  ): UniqueFileAccessInput[] {
    return uniqueFile.fileAccess.map((fileAccessKey) => {
      const fileAccessKeyMatch = /(u|g):(.+)(R|W|M)/.exec(fileAccessKey);
      assert.ok(fileAccessKeyMatch, `Invalid file access key: ${fileAccessKey}`);
      const [, granteeType, entityId, accessModifier] = fileAccessKeyMatch;
      assert.ok(
        granteeType && entityId && accessModifier,
        `Invalid file access key: ${fileAccessKey}`,
      );
      return {
        contentId: uniqueFile.id,
        accessType:
          ({ R: 'READ', W: 'WRITE', M: 'MANAGE' } as const)[accessModifier] ??
          assert.fail(`Invalid access modifier: ${accessModifier}`),
        entityId,
        entityType: granteeType === 'u' ? 'USER' : 'GROUP',
      };
    });
  }

  private mapSharePointPermissionsToUniqueFileAccessInputs(
    contentId: string,
    permissions: Membership[],
    uniqueGroupsMap: UniqueGroupsMap,
    uniqueUsersMap: UniqueUsersMap,
  ): UniqueFileAccessInput[] {
    const [userPermissions, groupPermissions] = partition(
      permissions,
      (permission) => permission.type === 'user',
    );

    const userAccessInputs: UniqueFileAccessInput[] = pipe(
      userPermissions,
      map((permission) => uniqueUsersMap[permission.email]),
      filter(isNonNullish),
      map(
        (uniqueUserId) =>
          ({
            contentId: contentId,
            accessType: 'READ',
            entityId: uniqueUserId,
            entityType: 'USER',
          }) as const,
      ),
    );

    const groupAccessInputs: UniqueFileAccessInput[] = pipe(
      groupPermissions,
      map((permission) => groupDistinctId(permission)),
      map((distinctId) => uniqueGroupsMap[distinctId]),
      filter(isNonNullish),
      map(
        (uniqueGroup) =>
          ({
            contentId: contentId,
            accessType: 'READ',
            entityId: uniqueGroup.id,
            entityType: 'GROUP',
          }) as const,
      ),
    );

    return [...userAccessInputs, ...groupAccessInputs];
  }
}
