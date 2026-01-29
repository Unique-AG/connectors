import type { Smeared } from '../../../utils/smeared';
import { DriveItem, ListItem } from './sharepoint.types';

interface BaseItem {
  siteId: Smeared<string>;
  driveId: string;
  driveName: string;
  folderPath: string;
  fileName: string;
}
export type SharepointContentItem = BaseItem &
  (
    | {
        itemType: 'driveItem';
        item: DriveItem;
      }
    | {
        itemType: 'listItem';
        item: ListItem;
      }
  );

export type SharepointDirectoryItem = BaseItem & {
  itemType: 'directory';
  item: DriveItem;
};

export type AnySharepointItem = SharepointContentItem | SharepointDirectoryItem;
