import type { Smeared } from '../../../utils/smeared';
import { DriveItem, ListItem } from './sharepoint.types';

// For a list item attachment, `driveId` is the list id, `driveName` the list folder name and
// `folderPath` the item folder within it.
interface BaseItem {
  siteId: Smeared;
  syncSiteId?: Smeared; // The ID of the top site that subsite items are ingested from
  driveId: string;
  driveName: string;
  folderPath: string;
  fileName: string;
}

interface ListItemAttachmentFile {
  absoluteUrl: string;
  size: number;
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
    | {
        itemType: 'listItemAttachment';
        item: ListItem;
        attachment: ListItemAttachmentFile;
        // Set when scanned from a discovered subsite. Unlike drive and SitePages URLs, the folder
        // path lacks the subsite, and SharePoint REST needs it to locate the list's web.
        subsiteRelativePath?: string;
      }
  );

export type SharepointDirectoryItem = BaseItem & {
  itemType: 'directory';
  item: DriveItem;
};

export type AnySharepointItem = SharepointContentItem | SharepointDirectoryItem;
