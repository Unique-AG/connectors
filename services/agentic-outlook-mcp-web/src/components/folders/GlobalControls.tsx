import dayjs from 'dayjs';
import LocalizedFormat from 'dayjs/plugin/localizedFormat';
import { AlertTriangle, Calendar, FolderSync, Globe, Mail, Trash2 } from 'lucide-react';
import { useMemo } from 'react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { FolderWithEmails } from '../../lib/powersync/schema';

dayjs.extend(LocalizedFormat);

interface GlobalControlsProps {
  syncEnabled: boolean;
  lastSyncedAt: string;
  folders: FolderWithEmails[];
  onToggleGlobalSync: (enabled: boolean) => void;
  onGlobalWipe: () => void;
  isLoading?: boolean;
}

export const GlobalControls = ({
  syncEnabled,
  lastSyncedAt,
  folders,
  onToggleGlobalSync,
  onGlobalWipe,
  isLoading = false,
}: GlobalControlsProps) => {
  const totalEmails = useMemo(
    () => folders.reduce((acc, folder) => acc + folder.emails.length, 0),
    [folders],
  );
  const syncedFolders = useMemo(
    () => folders.filter((folder) => folder.activatedAt && !folder.deactivatedAt),
    [folders],
  );
  const totalFolders = folders.length;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <Card className="shadow-medium">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="h-5 w-5 text-primary" />
            Sync Control
          </CardTitle>
          <CardDescription>Enable or disable sync for all folders</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="font-medium">Sync Status</div>
              <div className="text-sm text-muted-foreground">
                {syncEnabled ? 'All folder syncing enabled' : 'All folder syncing disabled'}
              </div>
            </div>
            <Switch
              checked={syncEnabled}
              onCheckedChange={onToggleGlobalSync}
              disabled={isLoading}
              className="data-[state=checked]:bg-primary"
            />
          </div>

          {lastSyncedAt && (
            <div className="pt-4 border-t">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Calendar className="h-4 w-4" />
                Last global sync: {dayjs(lastSyncedAt).format('lll')}
              </div>
            </div>
          )}

          {!syncEnabled && (
            <div className="p-3 bg-warning/10 border border-warning/20 rounded-lg">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-warning flex-shrink-0 mt-0.5" />
                <div className="text-sm">
                  <div className="font-medium text-warning">Sync disabled</div>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Statistics */}
      <Card className="shadow-medium">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderSync className="h-5 w-5 text-primary" />
            Sync Statistics
          </CardTitle>
          <CardDescription>Overview of your folder sync status</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="text-center p-3 bg-primary/5 rounded-lg">
              <div className="text-2xl font-bold text-primary">{syncedFolders.length}</div>
              <div className="text-sm text-muted-foreground">Active Folders</div>
            </div>
            <div className="text-center p-3 bg-muted rounded-lg">
              <div className="text-2xl font-bold text-foreground">{totalFolders}</div>
              <div className="text-sm text-muted-foreground">Total Folders</div>
            </div>
          </div>

          <div className="flex items-center gap-2 text-sm">
            <Mail className="h-4 w-4 text-primary" />
            <span className="font-medium">{totalEmails.toLocaleString()}</span>
            <span className="text-muted-foreground">emails synced</span>
          </div>

          <div className="w-full bg-muted rounded-full h-2">
            <div
              className="bg-gradient-primary h-2 rounded-full transition-all duration-300"
              style={{
                width: totalFolders > 0 ? `${(syncedFolders.length / totalFolders) * 100}%` : '0%',
              }}
            />
          </div>
        </CardContent>
      </Card>

      {/* Danger Zone */}
      <Card className="shadow-medium border-destructive/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <Trash2 className="h-5 w-5" />
            Danger Zone
          </CardTitle>
          <CardDescription>Irreversible actions that will permanently delete data</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="p-3 bg-destructive/5 border border-destructive/20 rounded-lg">
            <div className="flex items-start gap-2 mb-3">
              <AlertTriangle className="h-4 w-4 text-destructive flex-shrink-0 mt-0.5" />
              <div className="text-sm">
                <div className="font-medium text-destructive">Wipe All Data</div>
                <div className="text-muted-foreground">
                  Permanently delete all synced emails from all folders
                </div>
              </div>
            </div>

            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="destructive"
                  className="w-full"
                  disabled={isLoading || (totalEmails === 0 && totalFolders === 0)}
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Wipe All Data
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle className="flex items-center gap-2 text-destructive">
                    <AlertTriangle className="h-5 w-5" />
                    Confirm Global Data Wipe
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    This action will permanently delete all {totalEmails.toLocaleString()} synced
                    emails and all {totalFolders} folders. This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={onGlobalWipe}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    Yes, Wipe All Data
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>

          {totalEmails === 0 && totalFolders === 0 && (
            <div className="text-center text-sm text-muted-foreground">No data to wipe</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
