import { toCompilableQuery } from '@powersync/drizzle-driver';
import { useQuery } from '@powersync/react';
import { eq } from 'drizzle-orm';
import { useState } from 'react';
import { FolderTree } from '@/components/folders/FolderTree';
import { GlobalControls } from '@/components/folders/GlobalControls';
import { useCallApi } from '@/hooks/use-call-api';
import { useToast } from '@/hooks/use-toast';
import { deleteAllUserData, syncFolders } from '../@generated/sync/sync';
import { db } from '../lib/powersync/database';
import {
  UserProfile,
  userProfiles as userProfilesTable,
} from '../lib/powersync/schema';

export default function FolderManagement() {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();
  const { callApi } = useCallApi();

  // We only sync the user profile of the authenticated user
  const { data: userProfiles } = useQuery(toCompilableQuery(db.query.userProfiles.findFirst({})));
  // The type inference is broken. We need to manually cast it to UserProfile.
  const userProfile = userProfiles?.[0] as unknown as UserProfile;
  const syncEnabled = userProfile?.syncActivatedAt && !userProfile?.syncDeactivatedAt;

  const { data: folders } = useQuery(
    toCompilableQuery(
      db.query.folders.findMany({
        with: {
          emails: true,
        },
      }),
    ),
  );

  const handleResync = async () => {
    setIsRefreshing(true);

    try {
      const response = await callApi(syncFolders);

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
    if (!userProfile?.id) return;
    const query = enabled
      ? db
          .update(userProfilesTable)
          .set({ syncActivatedAt: new Date().toISOString(), syncDeactivatedAt: null })
          .where(eq(userProfilesTable.id, userProfile.id))
      : db.update(userProfilesTable).set({ syncDeactivatedAt: new Date().toISOString() });
    await toCompilableQuery(query).execute();
  };

  const handleGlobalWipe = async () => {
    setIsLoading(true);

    try {
      const response = await callApi(deleteAllUserData);

      if (response.status === 200) {
        toast({
          title: 'All Data Wiped',
          description: 'All synced emails and folders have been permanently deleted.',
        });
      }
    } catch (error) {
      toast({
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to wipe all data',
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
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
        syncEnabled={syncEnabled}
        lastSyncedAt={userProfile.syncLastSyncedAt}
        folders={folders}
        onToggleGlobalSync={handleToggleGlobalSync}
        onGlobalWipe={handleGlobalWipe}
        isLoading={isLoading}
      />

      <FolderTree
        syncEnabled={syncEnabled}
        folders={folders}
        onResync={handleResync}
        isRefreshing={isRefreshing}
      />
    </div>
  );
}
