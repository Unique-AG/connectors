import {
  Archive,
  ArchiveX,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderClock,
  FolderOpen,
  Inbox,
  PencilLine,
  SendHorizonal,
  Trash2,
} from 'lucide-react';
import { FC, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { type FolderWithChildren } from './FolderTree';

interface FolderItemProps {
  folder: FolderWithChildren;
  level: number;
  selectedFolderId?: string;
  onFolderSelect: (folderId: string) => void;
}

export const FolderItem: FC<FolderItemProps> = ({
  folder,
  level,
  selectedFolderId,
  onFolderSelect,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);

  const hasChildren = folder.children && folder.children.length > 0;
  const syncEnabled = folder.activatedAt && !folder.deactivatedAt;

  const customIconMap = {
    Inbox: <Inbox className="h-4 w-4 text-muted-foreground" />,
    Drafts: <PencilLine className="h-4 w-4 text-muted-foreground" />,
    'Sent Items': <SendHorizonal className="h-4 w-4 text-muted-foreground" />,
    Outbox: <FolderClock className="h-4 w-4 text-muted-foreground" />,
    'Deleted Items': <Trash2 className="h-4 w-4 text-muted-foreground" />,
    Archive: <Archive className="h-4 w-4 text-muted-foreground" />,
    'Junk Email': <ArchiveX className="h-4 w-4 text-muted-foreground" />,
  };

  const isSelected = selectedFolderId === folder.id;

  return (
    <div className="space-y-1">
      <button
        type="button"
        className={cn(
          'w-full flex items-center gap-2 p-2 rounded-md hover:bg-accent transition-colors text-left',
          isSelected && 'bg-accent',
        )}
        style={{ paddingLeft: `${level * 12 + 8}px` }}
        onClick={() => onFolderSelect(folder.id)}
      >
      {hasChildren && (
        // biome-ignore lint/a11y/noStaticElementInteractions: Cannot use nested button, using div with keyboard support instead
        <div
          className="flex-shrink-0 h-4 w-4 flex items-center justify-center hover:bg-muted rounded cursor-pointer"
          onClick={(e) => {
            e.stopPropagation();
            setIsExpanded(!isExpanded);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              e.stopPropagation();
              setIsExpanded(!isExpanded);
            }
          }}
        >
          {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </div>
      )}

        <div className="flex-shrink-0">
          {hasChildren ? (
            isExpanded ? (
              <FolderOpen className="h-4 w-4 text-primary" />
            ) : (
              <Folder className="h-4 w-4 text-muted-foreground" />
            )
          ) : (
            customIconMap[folder.name as keyof typeof customIconMap] || (
              <Folder className="h-4 w-4 text-muted-foreground" />
            )
          )}
        </div>

        <span className="flex-1 truncate text-sm">{folder.name}</span>

        <Badge variant="secondary" className="text-xs">
          {folder.emails?.length || 0}
        </Badge>

        {syncEnabled && (
          <Badge variant="outline" className="text-xs bg-success/10 text-success border-success/20">
            Active
          </Badge>
        )}
      </button>

      {hasChildren && isExpanded && (
        <div className="space-y-1">
          {folder.children.map((child) => (
            <FolderItem
              key={child.id}
              folder={child}
              level={level + 1}
              selectedFolderId={selectedFolderId}
              onFolderSelect={onFolderSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
};
