import {
  Calendar,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  Mail,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { OutlookFolder } from '@/types/folder';

interface FolderTreeProps {
  folders: OutlookFolder[];
  onToggleSync: (folderId: string, enabled: boolean) => void;
  onWipeFolder: (folderId: string) => void;
  onRefresh: () => void;
  isRefreshing?: boolean;
}

interface FolderItemProps {
  folder: OutlookFolder;
  level: number;
  onToggleSync: (folderId: string, enabled: boolean) => void;
  onWipeFolder: (folderId: string) => void;
}

const FolderItem = ({ folder, level, onToggleSync, onWipeFolder }: FolderItemProps) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const hasChildren = folder.children && folder.children.length > 0;

  const formatDate = (date?: Date) => {
    if (!date) return 'Never';
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  const getSyncStatusBadge = () => {
    if (folder.syncEnabled) {
      return (
        <Badge variant="outline" className="bg-success/10 text-success border-success/20">
          Active
        </Badge>
      );
    }
    return (
      <Badge variant="outline" className="bg-muted text-muted-foreground">
        Disabled
      </Badge>
    );
  };

  return (
    <div className="space-y-2">
      <Card
        className={cn(
          'transition-all duration-200 hover:shadow-medium',
          folder.syncEnabled && 'border-l-4 border-l-primary',
        )}
      >
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            {/* Expand/Collapse Button */}
            {hasChildren && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => setIsExpanded(!isExpanded)}
              >
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </Button>
            )}

            {/* Folder Icon */}
            <div className="flex-shrink-0">
              {hasChildren ? (
                isExpanded ? (
                  <FolderOpen className="h-5 w-5 text-primary" />
                ) : (
                  <Folder className="h-5 w-5 text-muted-foreground" />
                )
              ) : (
                <Folder className="h-5 w-5 text-muted-foreground" />
              )}
            </div>

            {/* Folder Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <h4 className="font-medium text-sm truncate">{folder.name}</h4>
                {getSyncStatusBadge()}
              </div>

              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                <div className="flex items-center gap-1">
                  <Mail className="h-3 w-3" />
                  {folder.emailCount} emails
                </div>

                {folder.syncEnabled && folder.syncActivatedAt && (
                  <div className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    Activated: {formatDate(folder.syncActivatedAt)}
                  </div>
                )}

                {folder.syncEnabled && folder.lastSyncAt && (
                  <div className="flex items-center gap-1">
                    <RefreshCw className="h-3 w-3" />
                    Last sync: {formatDate(folder.lastSyncAt)}
                  </div>
                )}

                {!folder.syncEnabled && folder.syncDeactivatedAt && (
                  <div className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    Deactivated: {formatDate(folder.syncDeactivatedAt)}
                  </div>
                )}
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-2">
              <Switch
                checked={folder.syncEnabled}
                onCheckedChange={(enabled) => onToggleSync(folder.id, enabled)}
                className="data-[state=checked]:bg-primary"
              />

              {!folder.syncEnabled && folder.emailCount > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onWipeFolder(folder.id)}
                  className="text-destructive hover:text-destructive-foreground hover:bg-destructive"
                >
                  <Trash2 className="h-3 w-3 mr-1" />
                  Wipe
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Child Folders */}
      {hasChildren && isExpanded && (
        <div className="ml-6 space-y-2">
          {folder.children!.map((child) => (
            <FolderItem
              key={child.id}
              folder={child}
              level={level + 1}
              onToggleSync={onToggleSync}
              onWipeFolder={onWipeFolder}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const FolderTree = ({
  folders,
  onToggleSync,
  onWipeFolder,
  onRefresh,
  isRefreshing = false,
}: FolderTreeProps) => {
  return (
    <Card className="shadow-medium">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <FolderOpen className="h-5 w-5 text-primary" />
            Outlook Folders
          </CardTitle>
          <Button
            onClick={onRefresh}
            variant="outline"
            disabled={isRefreshing}
            className="hover:bg-primary hover:text-primary-foreground"
          >
            <RefreshCw className={cn('h-4 w-4 mr-2', isRefreshing && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {folders.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Folder className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p>No folders found. Click refresh to sync with Outlook.</p>
          </div>
        ) : (
          folders.map((folder) => (
            <FolderItem
              key={folder.id}
              folder={folder}
              level={0}
              onToggleSync={onToggleSync}
              onWipeFolder={onWipeFolder}
            />
          ))
        )}
      </CardContent>
    </Card>
  );
};
