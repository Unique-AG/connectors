import { SharepointContentItem } from './sharepoint-content-item.interface';
import { DriveItem, ListItem } from './sharepoint.types';

export function isDriveItem(item: SharepointContentItem): item is SharepointContentItem & { item: DriveItem } {
  return item.itemType === 'driveItem';
}

export function isListItem(item: SharepointContentItem): item is SharepointContentItem & { item: ListItem } {
  return item.itemType === 'listItem';
}

export function isDriveItemFile(
  item: DriveItem,
): item is DriveItem & { file: { mimeType: string; hashes: { quickXorHash: string } } } {
  return !!item.file;
}
