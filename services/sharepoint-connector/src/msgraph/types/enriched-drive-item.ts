import type { DriveItem } from '@microsoft/microsoft-graph-types';

export interface EnrichedDriveItem extends DriveItem {
  siteId: string;
  driveId: string;
}
