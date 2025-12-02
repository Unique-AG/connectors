import { toCompilableQuery } from '@powersync/drizzle-driver';
import { useQuery } from '@powersync/react';
import { eq } from 'drizzle-orm';
import { useEffect, useMemo, useState } from 'react';
import { EmailDetail, EmailList, ErrorDialog } from '@/components/emails';
import { FolderTree } from '@/components/folders/FolderTree';
import { GlobalControls } from '@/components/folders/GlobalControls';
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable';
import { useCallApi } from '@/hooks/use-call-api';
import { useToast } from '@/hooks/use-toast';
import { EmailThread } from '@/types/email';
import { deleteAllUserData, syncFolderEmails, syncFolders } from '../@generated/sync/sync';
import { db } from '../lib/powersync/database';
import {
  Email,
  FolderWithEmails,
  folders as foldersTable,
  UserProfile,
  userProfiles as userProfilesTable,
} from '../lib/powersync/schema';

export default function FolderManagement() {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedFolderId, setSelectedFolderId] = useState<string | undefined>();
  const [selectedThreadId, setSelectedThreadId] = useState<string | undefined>();
  const [errorDialogOpen, setErrorDialogOpen] = useState(false);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const { toast } = useToast();
  const { callApi } = useCallApi();

  const { data: userProfiles } = useQuery(toCompilableQuery(db.query.userProfiles.findFirst({})));
  const userProfile = userProfiles?.[0] as unknown as UserProfile;
  const syncEnabled = userProfile?.syncActivatedAt && !userProfile?.syncDeactivatedAt;

  useEffect(() => {
    if (!syncEnabled) {
      setSelectedFolderId(undefined);
      setSelectedThreadId(undefined);
    }
  }, [syncEnabled]);

  const { data: folders } = useQuery(
    toCompilableQuery(
      db.query.folders.findMany({
        with: {
          emails: true,
        },
      }),
    ),
  );

  const selectedFolder = useMemo(() => {
    if (!selectedFolderId || !folders) return undefined;
    return folders.find((f) => f.id === selectedFolderId);
  }, [selectedFolderId, folders]);

  const threads = useMemo(() => {
    if (!selectedFolder?.emails) return [];

    const emailMap = new Map<string, Email[]>();

    for (const email of selectedFolder.emails) {
      const threadKey = email.conversationId || email.id;
      const existing = emailMap.get(threadKey) || [];
      existing.push(email);
      emailMap.set(threadKey, existing);
    }

    const result: EmailThread[] = [];
    for (const [threadId, emails] of emailMap) {
      const sortedEmails = emails.sort((a, b) => {
        const dateA = a.receivedAt ? new Date(a.receivedAt).getTime() : 0;
        const dateB = b.receivedAt ? new Date(b.receivedAt).getTime() : 0;
        return dateA - dateB;
      });

      const latestEmail = sortedEmails[sortedEmails.length - 1];
      result.push({
        id: threadId,
        subject: latestEmail.subject || '(No Subject)',
        emails: sortedEmails,
        lastDate: latestEmail.receivedAt ? new Date(latestEmail.receivedAt) : new Date(),
        isRead: sortedEmails.every((e) => e.isRead),
        hasAttachments: sortedEmails.some((e) => e.hasAttachments),
      });
    }

    return result.sort((a, b) => b.lastDate.getTime() - a.lastDate.getTime());
  }, [selectedFolder]);

  const selectedThread = useMemo(() => {
    return threads.find((t) => t.id === selectedThreadId);
  }, [threads, selectedThreadId]);

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

  const handleFolderResync = async (folderId: string) => {
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

  const handleWipeFolder = async (_folderId: string) => {
    toast({
      title: 'Folder Wipe',
      description: 'Folder wipe functionality coming soon.',
      variant: 'destructive',
    });
  };

  const handleReprocess = (emailId: string) => {
    toast({
      title: 'Processing email',
      description: `The email ${emailId} is being reprocessed...`,
    });
  };

  const handleErrorClick = (error: string) => {
    setSelectedError(error);
    setErrorDialogOpen(true);
  };

  if (!userProfile) return <div>Loading user...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-foreground mb-2">Email Management</h1>
        <p className="text-muted-foreground">
          Manage Outlook folder synchronization, view emails, and monitor processing status.
        </p>
      </div>

      <GlobalControls
        syncEnabled={syncEnabled}
        lastSyncedAt={userProfile.syncLastSyncedAt}
        folders={(folders as unknown as FolderWithEmails[]) || []}
        onToggleGlobalSync={handleToggleGlobalSync}
        onGlobalWipe={handleGlobalWipe}
        isLoading={isLoading}
      />

      <div className="h-[calc(100vh-20rem)]">
        <ResizablePanelGroup direction="horizontal">
          <ResizablePanel defaultSize={25} minSize={20} maxSize={35}>
            <FolderTree
              syncEnabled={syncEnabled}
              folders={(folders as unknown as FolderWithEmails[]) || []}
              selectedFolderId={selectedFolderId}
              onFolderSelect={setSelectedFolderId}
              onResync={handleResync}
              isRefreshing={isRefreshing}
            />
          </ResizablePanel>

          <ResizableHandle withHandle />

          <ResizablePanel defaultSize={30} minSize={20} maxSize={40}>
            <EmailList
              threads={threads}
              selectedFolder={selectedFolder}
              selectedThreadId={selectedThreadId}
              onThreadSelect={setSelectedThreadId}
              onErrorClick={handleErrorClick}
              onToggleSync={handleToggleFolderSync}
              onWipeFolder={handleWipeFolder}
              onResyncFolder={handleFolderResync}
            />
          </ResizablePanel>

          <ResizableHandle withHandle />

          <ResizablePanel defaultSize={45} minSize={30}>
            <EmailDetail emails={selectedThread?.emails || []} onReprocess={handleReprocess} />
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      <ErrorDialog open={errorDialogOpen} onOpenChange={setErrorDialogOpen} error={selectedError} />
    </div>
  );
}
