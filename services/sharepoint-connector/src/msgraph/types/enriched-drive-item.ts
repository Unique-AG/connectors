import type { DriveItem } from '@microsoft/microsoft-graph-types';

export interface EnrichedDriveItem extends DriveItem {
  id: string;
  name: string;
  size: number;
  webUrl: string;
  siteId: string;
  siteWebUrl: string;
  driveId: string;
  driveName: string;
  folderPath: string;
}
