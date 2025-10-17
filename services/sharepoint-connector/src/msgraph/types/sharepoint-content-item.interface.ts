import { DriveItem, ListItem } from './sharepoint.types';

interface BaseItem {
  siteId: string;
  siteWebUrl: string;
  driveId: string;
  driveName: string;
  folderPath: string;
  fileName: string;
}
export type SharepointContentItem = BaseItem & (
  {
    itemType: 'driveItem';
    item: DriveItem;
  } | {
    itemType: 'listItem';
    item: ListItem;
  })