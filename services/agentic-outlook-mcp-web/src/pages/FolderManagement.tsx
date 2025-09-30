import { toCompilableQuery } from '@powersync/drizzle-driver';
import { useQuery } from '@powersync/react';
import { useEffect, useState } from 'react';
import { FolderTree } from '@/components/folders/FolderTree';
import { GlobalControls } from '@/components/folders/GlobalControls';
import { useToast } from '@/hooks/use-toast';
import { OutlookFolder, SyncStats } from '@/types/folder';
import { db } from '../lib/powersync/database';

// Mock data for demonstration
const mockFolders: OutlookFolder[] = [
  {
    id: '1',
    name: 'Inbox',
    path: '/Inbox',
    syncEnabled: true,
    syncActivatedAt: new Date(Date.now() - 86400000 * 5), // 5 days ago
    lastSyncAt: new Date(Date.now() - 3600000), // 1 hour ago
    emailCount: 1247,
    totalEmailCount: 1247,
    children: [
      {
        id: '2',
        name: 'Important',
        path: '/Inbox/Important',
        parentId: '1',
        syncEnabled: true,
        syncActivatedAt: new Date(Date.now() - 86400000 * 3),
        lastSyncAt: new Date(Date.now() - 1800000), // 30 min ago
        emailCount: 23,
        totalEmailCount: 23,
      },
      {
        id: '3',
        name: 'Archive',
        path: '/Inbox/Archive',
        parentId: '1',
        syncEnabled: false,
        syncDeactivatedAt: new Date(Date.now() - 86400000 * 2),
        emailCount: 856,
        totalEmailCount: 856,
      },
    ],
  },
  {
    id: '4',
    name: 'Sent Items',
    path: '/Sent Items',
    syncEnabled: true,
    syncActivatedAt: new Date(Date.now() - 86400000 * 7),
    lastSyncAt: new Date(Date.now() - 7200000), // 2 hours ago
    emailCount: 432,
    totalEmailCount: 432,
  },
  {
    id: '5',
    name: 'Drafts',
    path: '/Drafts',
    syncEnabled: false,
    syncDeactivatedAt: new Date(Date.now() - 86400000),
    emailCount: 12,
    totalEmailCount: 12,
  },
  {
    id: '6',
    name: 'Projects',
    path: '/Projects',
    syncEnabled: true,
    syncActivatedAt: new Date(Date.now() - 86400000 * 10),
    lastSyncAt: new Date(Date.now() - 900000), // 15 min ago
    emailCount: 89,
    totalEmailCount: 267,
    children: [
      {
        id: '7',
        name: 'Project Alpha',
        path: '/Projects/Project Alpha',
        parentId: '6',
        syncEnabled: true,
        syncActivatedAt: new Date(Date.now() - 86400000 * 8),
        lastSyncAt: new Date(Date.now() - 1200000), // 20 min ago
        emailCount: 124,
        totalEmailCount: 124,
      },
      {
        id: '8',
        name: 'Project Beta',
        path: '/Projects/Project Beta',
        parentId: '6',
        syncEnabled: false,
        syncDeactivatedAt: new Date(Date.now() - 86400000 * 3),
        emailCount: 54,
        totalEmailCount: 54,
      },
    ],
  },
];

export default function FolderManagement() {
  // const [folders, setFolders] = useState<OutlookFolder[]>(mockFolders);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();

  const { data: folders } = useQuery(toCompilableQuery(db.query.folders.findMany()));
  const { data: syncJobs, isLoading: isSyncJobsLoading } = useQuery(toCompilableQuery(db.query.syncJobs.findMany()));

  console.log(folders);

  // Calculate statistics
  const calculateStats = (folders: OutlookFolder[]): SyncStats => {
    const getAllFolders = (folders: OutlookFolder[]): OutlookFolder[] => {
      let result: OutlookFolder[] = [];
      for (const folder of folders) {
        result.push(folder);
        if (folder.children) {
          result = result.concat(getAllFolders(folder.children));
        }
      }
      return result;
    };

    const allFolders = getAllFolders(folders);
    const syncedFolders = allFolders.filter((f) => f.syncEnabled);
    const totalEmails = allFolders.reduce((sum, f) => sum + f.emailCount, 0);

    const lastSyncDates = syncedFolders
      .map((f) => f.lastSyncAt)
      .filter((date) => date !== undefined) as Date[];

    const lastGlobalSync =
      lastSyncDates.length > 0
        ? new Date(Math.max(...lastSyncDates.map((d) => d.getTime())))
        : undefined;

    return {
      totalFolders: allFolders.length,
      syncedFolders: syncedFolders.length,
      totalEmails,
      lastGlobalSync,
      globalSyncEnabled: syncedFolders.length > 0,
    };
  };

  const [stats, setStats] = useState<SyncStats>(calculateStats(folders));

  useEffect(() => {
    setStats(calculateStats(folders));
  }, [folders]);

  const handleToggleSync = async (folderId: string, enabled: boolean) => {
    setIsLoading(true);

    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 500));

    const updateFolder = (folders: OutlookFolder[]): OutlookFolder[] => {
      return folders.map((folder) => {
        if (folder.id === folderId) {
          return {
            ...folder,
            syncEnabled: enabled,
            syncActivatedAt: enabled ? new Date() : folder.syncActivatedAt,
            syncDeactivatedAt: enabled ? undefined : new Date(),
            lastSyncAt: enabled ? new Date() : folder.lastSyncAt,
          };
        }
        if (folder.children) {
          return {
            ...folder,
            children: updateFolder(folder.children),
          };
        }
        return folder;
      });
    };

    // setFolders(updateFolder(folders));
    setIsLoading(false);

    toast({
      title: enabled ? 'Sync Enabled' : 'Sync Disabled',
      description: `Folder sync has been ${enabled ? 'enabled' : 'disabled'} successfully.`,
    });
  };

  const handleWipeFolder = async (folderId: string) => {
    setIsLoading(true);

    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 1000));

    const updateFolder = (folders: OutlookFolder[]): OutlookFolder[] => {
      return folders.map((folder) => {
        if (folder.id === folderId) {
          return {
            ...folder,
            emailCount: 0,
          };
        }
        if (folder.children) {
          return {
            ...folder,
            children: updateFolder(folder.children),
          };
        }
        return folder;
      });
    };

    // setFolders(updateFolder(folders));
    setIsLoading(false);

    toast({
      title: 'Folder Wiped',
      description: 'All emails have been permanently deleted from the folder.',
      variant: 'destructive',
    });
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);

    // Simulate API call to refresh folder structure
    await new Promise((resolve) => setTimeout(resolve, 2000));

    setIsRefreshing(false);

    toast({
      title: 'Folders Refreshed',
      description: 'Folder structure has been updated from Outlook.',
    });
  };

  const handleToggleGlobalSync = async (enabled: boolean) => {
    setIsLoading(true);

    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 1000));

    const updateAllFolders = (folders: OutlookFolder[]): OutlookFolder[] => {
      return folders.map((folder) => ({
        ...folder,
        syncEnabled: enabled,
        syncActivatedAt: enabled ? new Date() : folder.syncActivatedAt,
        syncDeactivatedAt: enabled ? undefined : new Date(),
        lastSyncAt: enabled ? new Date() : folder.lastSyncAt,
        children: folder.children ? updateAllFolders(folder.children) : undefined,
      }));
    };

    // setFolders(updateAllFolders(folders));
    setIsLoading(false);

    toast({
      title: enabled ? 'Global Sync Enabled' : 'Global Sync Disabled',
      description: `All folder syncing has been ${enabled ? 'enabled' : 'disabled'}.`,
    });
  };

  const handleGlobalWipe = async () => {
    setIsLoading(true);

    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 2000));

    const wipeAllFolders = (folders: OutlookFolder[]): OutlookFolder[] => {
      return folders.map((folder) => ({
        ...folder,
        emailCount: 0,
        children: folder.children ? wipeAllFolders(folder.children) : undefined,
      }));
    };

    // setFolders(wipeAllFolders(folders));
    setIsLoading(false);

    toast({
      title: 'All Data Wiped',
      description: 'All synced emails have been permanently deleted.',
      variant: 'destructive',
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-foreground mb-2">Folder Management</h1>
        <p className="text-muted-foreground">
          Manage your Outlook folder synchronization settings and monitor sync status.
        </p>
      </div>

      <GlobalControls
        stats={stats}
        onToggleGlobalSync={handleToggleGlobalSync}
        onGlobalWipe={handleGlobalWipe}
        isLoading={isLoading || isSyncJobsLoading}
      />

      <FolderTree
        folders={folders}
        onToggleSync={handleToggleSync}
        onWipeFolder={handleWipeFolder}
        onRefresh={handleRefresh}
        isRefreshing={isRefreshing}
      />
    </div>
  );
}
