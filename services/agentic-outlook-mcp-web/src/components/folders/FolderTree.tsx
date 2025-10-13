import dayjs from 'dayjs';
import LocalizedFormat from 'dayjs/plugin/localizedFormat';
import { Folder, FolderOpen, RefreshCw } from 'lucide-react';
import { useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { FolderWithEmails } from '../../lib/powersync/schema';
import { FolderItem } from './FolderItem';

dayjs.extend(LocalizedFormat);

export type FolderWithChildren = FolderWithEmails & { children: FolderWithChildren[] };

interface FolderTreeProps {
  syncEnabled: boolean;
  folders: FolderWithEmails[];
  onResync: () => void;
  isRefreshing?: boolean;
}

// Outlook does now provide a sort order via api for folders. So we need to sort them manually.
const defaultOutlookFolderSort = [
  'Inbox',
  'Drafts',
  'Sent Items',
  'Outbox',
  'Archive',
  'Deleted Items',
  'Conversation History',
  'Junk Email',
];

const buildFolderTree = (folders: FolderWithEmails[]): FolderWithChildren[] => {
  const folderMap = new Map<string, FolderWithChildren>();
  const rootFolders: FolderWithChildren[] = [];

  folders.forEach((folder) => {
    folderMap.set(folder.folderId, { ...folder, children: [] });
  });

  folders.forEach((folder) => {
    const folderWithChildren = folderMap.get(folder.folderId);
    if (!folderWithChildren) return;

    if (folder.parentFolderId) {
      const parent = folderMap.get(folder.parentFolderId);
      if (parent) {
        parent.children.push(folderWithChildren);
      } else {
        rootFolders.push(folderWithChildren);
      }
    } else {
      rootFolders.push(folderWithChildren);
    }
  });

  // Sort the folders by the default Outlook folder sort order then by name
  rootFolders.sort((a, b) => {
    const aIndex = defaultOutlookFolderSort.indexOf(a.name);
    const bIndex = defaultOutlookFolderSort.indexOf(b.name);

    const aInList = aIndex !== -1;
    const bInList = bIndex !== -1;

    if (aInList && bInList) {
      return aIndex - bIndex;
    }

    if (aInList) return -1;
    if (bInList) return 1;

    return a.name.localeCompare(b.name);
  });

  return rootFolders;
};

export const FolderTree = ({
  syncEnabled,
  folders,
  onResync,
  isRefreshing = false,
}: FolderTreeProps) => {
  const folderTree = useMemo(() => buildFolderTree(folders), [folders]);

  return (
    <div className="relative">
      <Card className="shadow-medium">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5 text-primary" />
              Outlook Folders
            </CardTitle>
            <Button
              onClick={onResync}
              variant="outline"
              disabled={isRefreshing}
              className="hover:bg-primary hover:text-primary-foreground"
            >
              <RefreshCw className={cn('h-4 w-4 mr-2', isRefreshing && 'animate-spin')} />
              Resync Folders
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {folders.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Folder className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No folders found. Click resync to sync with Outlook.</p>
            </div>
          ) : (
            folderTree.map((folder) => (
              <FolderItem
                key={folder.id}
                folder={folder}
                level={0}
              />
            ))
          )}
        </CardContent>
      </Card>

      {!syncEnabled && (
        <div className="absolute inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center rounded-lg">
          <div className="text-center space-y-2 p-6">
            <FolderOpen className="h-12 w-12 mx-auto text-muted-foreground opacity-50" />
            <div className="text-lg font-semibold text-foreground">Sync is Disabled</div>
            <p className="text-sm text-muted-foreground max-w-md">
              Enable sync in the Sync Control section above to start syncing folders from Outlook.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
