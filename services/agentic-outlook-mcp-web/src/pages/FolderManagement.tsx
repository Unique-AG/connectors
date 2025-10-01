import { toCompilableQuery } from '@powersync/drizzle-driver';
import { useQuery } from '@powersync/react';
import { useState } from 'react';
import { foldersControllerUpdateFolders } from '@/@generated/folders/folders';
import { syncControllerCreateSyncJob } from '@/@generated/sync/sync';
import { FolderTree } from '@/components/folders/FolderTree';
import { GlobalControls } from '@/components/folders/GlobalControls';
import { useCallApi } from '@/hooks/use-call-api';
import { useToast } from '@/hooks/use-toast';
import { db } from '../lib/powersync/database';
import { UserProfile } from '../lib/powersync/schema';

export default function FolderManagement() {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();
  const { callApi } = useCallApi();

  // We only sync the user profile of the authenticated user
  const { data: userProfiles } = useQuery(toCompilableQuery(db.query.userProfiles.findFirst({})));
  const userProfile = userProfiles?.[0];

  const { data: folders } = useQuery(
    toCompilableQuery(
      db.query.folders.findMany({
        with: {
          emails: true,
        },
      }),
    ),
  );

  const handleToggleSync = async (folderId: string, enabled: boolean) => {
    setIsLoading(true);

    // try {
    //   if (enabled) {
    //     const response = await callApi(syncControllerCreateSyncJob);

    //     if (response.status === 201) {
    //       toast({
    //         title: 'Sync Enabled',
    //         description: 'Folder sync has been enabled successfully.',
    //       });
    //     }
    //   }
    // } catch (error) {
    //   toast({
    //     title: 'Error',
    //     description: error instanceof Error ? error.message : 'Failed to toggle sync',
    //     variant: 'destructive',
    //   });
    //   setIsLoading(false);
    //   return;
    // }

    setIsLoading(false);

    if (!enabled) {
      toast({
        title: 'Sync Disabled',
        description: 'Folder sync has been disabled successfully.',
      });
    }
  };

  const handleWipeFolder = async (folderId: string) => {
    setIsLoading(true);

    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 1000));

    setIsLoading(false);

    toast({
      title: 'Folder Wiped',
      description: 'All emails have been permanently deleted from the folder.',
      variant: 'destructive',
    });
  };

  const handleResync = async () => {
    setIsRefreshing(true);

    try {
      const response = await callApi(foldersControllerUpdateFolders);

      if (response.status === 200) {
        toast({
          title: 'Folders Refreshed',
          description: 'Folder structure has been updated from Outlook.',
        });
      }
    } catch (error) {
      toast({
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to refresh folders',
        variant: 'destructive',
      });
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleToggleGlobalSync = async (enabled: boolean) => {
    setIsLoading(true);

    try {
      if (enabled) {
        const response = await callApi(syncControllerCreateSyncJob);

        if (response.status === 201) {
          toast({
            title: 'Sync Enabled',
            description: 'All folder syncing has been enabled.',
          });
        }
      }
    } catch (error) {
      toast({
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to toggle sync',
        variant: 'destructive',
      });
      setIsLoading(false);
      return;
    }

    setIsLoading(false);

    if (!enabled) {
      toast({
        title: 'Sync Disabled',
        description: 'All folder syncing has been disabled.',
      });
    }
  };

  const handleGlobalWipe = async () => {
    setIsLoading(true);

    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 2000));

    setIsLoading(false);

    toast({
      title: 'All Data Wiped',
      description: 'All synced emails have been permanently deleted.',
      variant: 'destructive',
    });
  };

  if (!userProfile) return <div>Loading...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-foreground mb-2">Folder Management</h1>
        <p className="text-muted-foreground">
          Manage your Outlook folder synchronization settings and monitor sync status.
        </p>
      </div>

      <GlobalControls
        userProfile={userProfile as unknown as UserProfile}
        folders={folders}
        onToggleGlobalSync={handleToggleGlobalSync}
        onGlobalWipe={handleGlobalWipe}
        isLoading={isLoading}
      />

      <FolderTree
        folders={folders}
        onToggleSync={handleToggleSync}
        onWipeFolder={handleWipeFolder}
        onResync={handleResync}
        isRefreshing={isRefreshing}
      />
    </div>
  );
}
