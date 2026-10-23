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
        // Set when the item was scanned from a discovered subsite. Drive and SitePages items keep
        // the subsite in their URL, so only attachments need it carried explicitly. Also locates
        // the web that owns the list, which SharePoint REST needs to download the attachment.
        subsiteRelativePath?: string;
      }
  );

export type SharepointDirectoryItem = BaseItem & {
  itemType: 'directory';
  item: DriveItem;
};

export type AnySharepointItem = SharepointContentItem | SharepointDirectoryItem;
