import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Counter, ValueType } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
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
import { Config } from '../config';
import { SharepointSyncContext } from '../sharepoint-synchronization/types';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueFile, UniqueFileAccessInput } from '../unique-api/unique-files/unique-files.types';
import { shouldConcealLogs, smear } from '../utils/logging.util';
import { Membership, UniqueGroupsMap, UniqueUsersMap } from './types';
import { groupDistinctId } from './utils';

interface Input {
  context: SharepointSyncContext;
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
  private readonly shouldConcealLogs: boolean;

  private readonly spcPermissionsSyncFileOperationsTotal: Counter;

  public constructor(
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly configService: ConfigService<Config, true>,
    metricService: MetricService,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);

    this.spcPermissionsSyncFileOperationsTotal = metricService.getCounter(
      'spc_permissions_sync_file_operations_total',
      {
        description: 'Number of permissions changing operations performed on Unique files',
        valueType: ValueType.INT,
      },
    );
  }

  public async run(input: Input): Promise<void> {
    const { context, sharePoint, unique } = input;
    const { siteId, serviceUserId } = context;

    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;
    this.logger.log(
      `${logPrefix} Starting permissions sync for ` +
        `${Object.keys(sharePoint.permissionsMap).length} items`,
    );

    this.logger.log(`${logPrefix} Fetching unique files`);
    const uniqueFiles = await this.uniqueFilesService.getFilesForSite(siteId);
    this.logger.log(`${logPrefix} Fetched ${uniqueFiles.length} unique files`);
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
        // We need to ensure we do not remove the service user's access to file. It won't be present
        // in SharePoint, but should be present in Unique, so we filter out any removals for the
        // service user.
        ({ entityType, entityId }) => !(entityType === 'USER' && entityId === serviceUserId),
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
    let totalPermissionsAdded = 0;
    for (const [scopeId, permissionsToAdd] of Object.entries(permissionsToAddByScopeId)) {
      this.logger.debug(
        `${logPrefix}[Scope: ${scopeId}] Adding ${permissionsToAdd.length} permissions`,
      );
      await this.uniqueFilesService.addAccesses(scopeId, permissionsToAdd);
      totalPermissionsAdded += permissionsToAdd.length;
    }

    this.logger.log(
      `${logPrefix} Removing permissions from unique files in ${Object.keys(permissionsToRemoveByScopeId).length} scopes`,
    );
    let totalPermissionsRemoved = 0;
    for (const [scopeId, permissionsToRemove] of Object.entries(permissionsToRemoveByScopeId)) {
      this.logger.debug(
        `${logPrefix}[Scope: ${scopeId}] Removing ${permissionsToRemove.length} permissions`,
      );
      await this.uniqueFilesService.removeAccesses(scopeId, permissionsToRemove);
      totalPermissionsRemoved += permissionsToRemove.length;
    }

    if (totalPermissionsAdded > 0) {
      this.spcPermissionsSyncFileOperationsTotal.add(totalPermissionsAdded, {
        sp_site_id: siteId,
        operation: 'added',
      });
    }
    if (totalPermissionsRemoved > 0) {
      this.spcPermissionsSyncFileOperationsTotal.add(totalPermissionsRemoved, {
        sp_site_id: siteId,
        operation: 'removed',
      });
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

      const accessType =
        ({ r: 'READ', w: 'WRITE', m: 'MANAGE' } as const)[accessModifier.toLowerCase()] ??
        assert.fail(`Invalid access modifier: ${accessModifier} in key ${fileAccessKey}`);
      return {
        contentId: uniqueFile.id,
        accessType,
        entityId,
        entityType: granteeType.toLowerCase() === 'u' ? 'USER' : 'GROUP',
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
