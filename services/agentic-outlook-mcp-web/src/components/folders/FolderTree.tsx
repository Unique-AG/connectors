import { Folder, FolderOpen, RefreshCw } from 'lucide-react';
import { useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { FolderWithEmails } from '../../lib/powersync/schema';
import { FolderItem } from './FolderItem';

export type FolderWithChildren = FolderWithEmails & { children: FolderWithChildren[] };

interface FolderTreeProps {
  syncEnabled: boolean;
  folders: FolderWithEmails[];
  selectedFolderId?: string;
  onFolderSelect: (folderId: string) => void;
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
  selectedFolderId,
  onFolderSelect,
  onResync,
  isRefreshing = false,
}: FolderTreeProps) => {
  const folderTree = useMemo(() => buildFolderTree(folders), [folders]);

  return (
    <div className="h-full bg-card overflow-y-auto relative">
      <div className="p-4 border-b sticky top-0 bg-card z-10">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <FolderOpen className="h-5 w-5 text-primary" />
            Folders
          </h2>
          <Button
            onClick={onResync}
            variant="ghost"
            size="sm"
            disabled={isRefreshing}
          >
            <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
          </Button>
        </div>
      </div>
      <div className="p-2 space-y-1">
        {folders.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Folder className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p className="text-sm">No folders found</p>
          </div>
        ) : (
          folderTree.map((folder) => (
            <FolderItem
              key={folder.id}
              folder={folder}
              level={0}
              selectedFolderId={selectedFolderId}
              onFolderSelect={onFolderSelect}
            />
          ))
        )}
      </div>

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
