import { Injectable, Logger } from '@nestjs/common';
import { isNullish } from 'remeda';
import { SharepointDirectoryItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { buildIngestionItemKey, getUniquePathFromItem } from '../utils/sharepoint.util';
import { Smeared } from '../utils/smeared';
import { Membership } from './types';
import { isTopFolder } from './utils';

interface Input {
  directories: SharepointDirectoryItem[];
  permissionsMap: Record<string, Membership[]>;
  rootPath: Smeared;
}

@Injectable()
export class GetRegularFolderPermissionsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public run(input: Input): Map<string, Membership[]> {
    const { directories, permissionsMap, rootPath } = input;

    const result = new Map<string, Membership[]>();

    for (const directory of directories) {
      const folderPath = getUniquePathFromItem(directory, rootPath);

      if (isTopFolder(folderPath, rootPath)) {
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
