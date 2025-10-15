import {PipelineItem} from "./pipeline-item.interface";
import {DriveItem, ListItem} from "./sharepoint.types";

export function isDriveItem(item: PipelineItem): item is PipelineItem & { item: DriveItem } {
  return item.itemType === 'driveItem';
}

export function isListItem(item: PipelineItem): item is PipelineItem & { item: ListItem } {
  return item.itemType === 'listItem';
}

export function isDriveItemFile(item: DriveItem): item is DriveItem & { file: { mimeType: string; hashes: { quickXorHash: string } } } {
  return !!item.file;
}