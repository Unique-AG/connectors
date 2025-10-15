import {DriveItem, ListItem} from "./sharepoint.types";

// This can be named something like ItemToProcess
export interface PipelineItem {
  itemType: 'listItem' | 'driveItem';
  item: DriveItem | ListItem;
  siteId: string;
  siteWebUrl: string;
  driveId: string;
  driveName: string;
  folderPath: string;
  fileName: string;
}