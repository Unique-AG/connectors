import { DriveItem, ListItem } from './sharepoint.types';

export interface SharepointContentItem {
  itemType: 'listItem' | 'driveItem';
  item: DriveItem | ListItem;
  siteId: string;
  siteWebUrl: string;
  driveId: string;
  driveName: string;
  folderPath: string;
  fileName: string;
}
