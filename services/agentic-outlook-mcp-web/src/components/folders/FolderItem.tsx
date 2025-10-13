import { toCompilableQuery } from '@powersync/drizzle-driver';
import dayjs from 'dayjs';
import LocalizedFormat from 'dayjs/plugin/localizedFormat';
import { eq } from 'drizzle-orm';
import {
  Archive,
  ArchiveX,
  Calendar,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderClock,
  FolderOpen,
  Inbox,
  Mail,
  PencilLine,
  RefreshCw,
  SendHorizonal,
  Trash2,
} from 'lucide-react';
import { FC, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { useCallApi } from '@/hooks/use-call-api';
import { useToast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';
import { syncFolderEmails } from '../../@generated/sync/sync';
import { db } from '../../lib/powersync/database';
import { folders as foldersTable } from '../../lib/powersync/schema';
import { type FolderWithChildren } from './FolderTree';

dayjs.extend(LocalizedFormat);

interface FolderItemProps {
  folder: FolderWithChildren;
  level: number;
}

export const FolderItem: FC<FolderItemProps> = ({ folder, level }) => {
  const [isExpanded, setIsExpanded] = useState(true);
  const { toast } = useToast();
  const { callApi } = useCallApi();
  const [isLoading, setIsLoading] = useState(false);

  const hasChildren = folder.children && folder.children.length > 0;
  const syncEnabled = folder.activatedAt && !folder.deactivatedAt;

  const customIconMap = {
    Inbox: <Inbox className="h-5 w-5 text-muted-foreground" />,
    Drafts: <PencilLine className="h-5 w-5 text-muted-foreground" />,
    'Sent Items': <SendHorizonal className="h-5 w-5 text-muted-foreground" />,
    Outbox: <FolderClock className="h-5 w-5 text-muted-foreground" />,
    'Deleted Items': <Trash2 className="h-5 w-5 text-muted-foreground" />,
    Archive: <Archive className="h-5 w-5 text-muted-foreground" />,
    'Junk Email': <ArchiveX className="h-5 w-5 text-muted-foreground" />,
  };

  const getSyncStatusBadge = () => {
    if (syncEnabled) {
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

  const handleToggleFolderSync = async (folderId: string, enabled: boolean) => {
    const query = enabled
      ? db
          .update(foldersTable)
          .set({ activatedAt: new Date().toISOString(), deactivatedAt: null })
          .where(eq(foldersTable.id, folderId))
      : db
          .update(foldersTable)
          .set({ deactivatedAt: new Date().toISOString() })
          .where(eq(foldersTable.id, folderId));
    await toCompilableQuery(query).execute();
  };

  const handleResync = async (folderId: string) => {
    setIsLoading(true);
    try {
      const response = await callApi(syncFolderEmails, folderId);
      if (response.status === 200) {
        toast({
          title: 'Folder Resynced',
          description: 'All emails have been resynced from the folder.',
        });
      }
    } catch (error) {
      toast({
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to resync folder',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleWipeFolder = async (folderId: string) => {
    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 1000));

    toast({
      title: 'Folder Wiped',
      description: 'All emails have been permanently deleted from the folder.',
      variant: 'destructive',
    });
  };

  return (
    <div className="space-y-2">
      <Card
        className={cn(
          'transition-all duration-200 hover:shadow-medium',
          syncEnabled && 'border-l-4 border-l-primary',
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
                customIconMap[folder.name as keyof typeof customIconMap] || (
                  <Folder className="h-5 w-5 text-muted-foreground" />
                )
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
                  {folder.emails?.length || 0} emails
                </div>

                {syncEnabled && folder.activatedAt && (
                  <div className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    Activated: {dayjs(folder.activatedAt).format('lll')}
                  </div>
                )}

                {syncEnabled && folder.lastSyncedAt && (
                  <div className="flex items-center gap-1">
                    <RefreshCw className="h-3 w-3" />
                    Last sync: {dayjs(folder.lastSyncedAt).format('lll')}
                  </div>
                )}

                {!syncEnabled && folder.deactivatedAt && (
                  <div className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    Deactivated: {dayjs(folder.deactivatedAt).format('lll')}
                  </div>
                )}
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-2">
              <Switch
                checked={syncEnabled}
                onCheckedChange={(enabled) => handleToggleFolderSync(folder.id, enabled)}
                className="data-[state=checked]:bg-primary"
              />

              {syncEnabled && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleResync(folder.id)}
                  className="text-primary hover:text-primary-foreground hover:bg-primary"
                  disabled={isLoading}
                >
                  <RefreshCw className="h-3 w-3 mr-1" />
                  Resync
                </Button>
              )}

              {!syncEnabled && !!folder.emails?.length && folder.emails.length > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleWipeFolder(folder.id)}
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
          {folder.children.map((child) => (
            <FolderItem
              key={child.id}
              folder={child}
              level={level + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
};
