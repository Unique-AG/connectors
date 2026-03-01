import { Injectable, Logger } from '@nestjs/common';
import { isNullish, prop } from 'remeda';
import { SharepointDirectoryItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { DiscoveredSubsite } from '../sharepoint-synchronization/subsite-discovery.service';
import { buildIngestionItemKey, getUniquePathFromItem } from '../utils/sharepoint.util';
import { Smeared } from '../utils/smeared';
import { Membership } from './types';
import { isTopFolder } from './utils';

interface Input {
  directories: SharepointDirectoryItem[];
  permissionsMap: Record<string, Membership[]>;
  rootPath: Smeared;
  siteName: Smeared;
  discoveredSubsites: DiscoveredSubsite[];
}

@Injectable()
export class GetRegularFolderPermissionsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public run(input: Input): Map<string, Membership[]> {
    const { directories, permissionsMap, rootPath, siteName, discoveredSubsites } = input;
    const subsiteRelativePaths = discoveredSubsites.map(prop('relativePath')).map(prop('value'));

    const result = new Map<string, Membership[]>();

    for (const directory of directories) {
      const folderPath = getUniquePathFromItem(directory, rootPath, siteName);

      if (isTopFolder(folderPath, rootPath, subsiteRelativePaths)) {
        continue;
      }

      const permissionsKey = buildIngestionItemKey(directory);
      const permissions = permissionsMap[permissionsKey];

      if (isNullish(permissions)) {
        this.logger.warn(
          `No SharePoint permissions found for directory with key ${permissionsKey}`,
        );
        continue;
      }

      result.set(folderPath.value, permissions);
    }

    return result;
  }
}
