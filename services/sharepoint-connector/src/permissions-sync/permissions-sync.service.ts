import { Injectable, Logger } from '@nestjs/common';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { elapsedSecondsLog } from '../utils/timing.util';
import { FetchGraphPermissionsMapQuery } from './fetch-graph-permissions-map.query';

@Injectable()
export class PermissionsSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly fetchGraphPermissionsMapQuery: FetchGraphPermissionsMapQuery,
  ) {}

  public async syncPermissionsForSite(
    siteId: string,
    items: SharepointContentItem[],
  ): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}] `;
    this.logger.log(`${logPrefix} Starting permissions fetching for ${items.length} items`);
    const permissionsFetchStartTime = Date.now();
    const permissionsMap = await this.fetchGraphPermissionsMapQuery.run(siteId, items);
    this.logger.log(
      `${logPrefix} Fetched permissions for ${items.length} items in ${elapsedSecondsLog(permissionsFetchStartTime)}`,
    );
    this.logger.log(`${logPrefix} Permissions map length: ${Object.keys(permissionsMap).length}`);
  }
}
