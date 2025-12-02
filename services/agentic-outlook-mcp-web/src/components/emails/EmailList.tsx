import { format, formatDistanceToNow } from 'date-fns';
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  Clock,
  Mail,
  Paperclip,
  RefreshCw,
  Trash2,
  XCircle,
} from 'lucide-react';
import numeral from 'numeral';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { FolderWithEmails } from '@/lib/powersync/schema';
import { cn } from '@/lib/utils';
import { EmailThread, getProcessingStatus, ProcessingStatus, parseFromField } from '@/types/email';


interface EmailListProps {
  threads: EmailThread[];
  selectedFolder?: FolderWithEmails;
  selectedThreadId?: string;
  onThreadSelect: (threadId: string) => void;
  onErrorClick: (error: string) => void;
  onToggleSync: (folderId: string, enabled: boolean) => void;
  onWipeFolder: (folderId: string) => void;
  onResyncFolder: (folderId: string) => void;
}

export const EmailList = ({
  threads,
  selectedFolder,
  selectedThreadId,
  onThreadSelect,
  onErrorClick,
  onToggleSync,
  onWipeFolder,
  onResyncFolder,
}: EmailListProps) => {
  

  const syncEnabled = selectedFolder?.activatedAt && !selectedFolder?.deactivatedAt;

  return (
    <div className="h-full bg-card border-r overflow-y-auto">
      {selectedFolder ? (
        <div className="p-4 border-b space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">{selectedFolder.name}</h2>
              <p className="text-sm text-muted-foreground">{numeral(threads.length).format('0,0')} threads</p>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                checked={syncEnabled}
                onCheckedChange={(enabled) => onToggleSync(selectedFolder.id, enabled)}
                className="data-[state=checked]:bg-primary"
              />
              <span className="text-sm text-muted-foreground">
                {syncEnabled ? 'Active' : 'Disabled'}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Mail className="h-4 w-4" />
              <span>{numeral(selectedFolder.emails?.length || 0).format('0,0')} emails</span>
            </div>

            {syncEnabled && selectedFolder.lastSyncedAt && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Calendar className="h-4 w-4" />
                <span>Last sync: {format(new Date(selectedFolder.lastSyncedAt), 'MMM d, yyyy h:mm a')}</span>
              </div>
            )}

            {syncEnabled && selectedFolder.activatedAt && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Calendar className="h-4 w-4" />
                <span>Activated: {format(new Date(selectedFolder.activatedAt), 'MMM d, yyyy h:mm a')}</span>
              </div>
            )}

            {!syncEnabled && selectedFolder.deactivatedAt && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Calendar className="h-4 w-4" />
                <span>Deactivated: {format(new Date(selectedFolder.deactivatedAt), 'MMM d, yyyy h:mm a')}</span>
              </div>
            )}
          </div>

          <div className="flex gap-2">
            {syncEnabled && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onResyncFolder(selectedFolder.id)}
                className="flex-1"
              >
                <RefreshCw className="h-4 w-4 mr-2" />
                Resync Folder
              </Button>
            )}
            {!syncEnabled && selectedFolder.emails && selectedFolder.emails.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onWipeFolder(selectedFolder.id)}
                className="flex-1 text-destructive hover:text-destructive-foreground hover:bg-destructive"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Wipe Folder Data
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div className="p-4 border-b">
          <h2 className="text-lg font-semibold">Emails</h2>
          <p className="text-sm text-muted-foreground">Select a folder to view emails</p>
        </div>
      )}
      <div>
        {threads.map((thread) => {
          const latestEmail = thread.emails[thread.emails.length - 1];
          const processStatus = getProcessingStatus(latestEmail);
          const from = parseFromField(latestEmail.from);

          return (
            <button
              type="button"
              key={thread.id}
              onClick={() => onThreadSelect(thread.id)}
              className={cn(
                'w-full text-left p-4 border-b hover:bg-accent transition-colors',
                selectedThreadId === thread.id && 'bg-accent',
                !thread.isRead && 'bg-accent/30',
              )}
            >
              <div className="flex items-start justify-between gap-2 mb-1">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className={cn('font-medium truncate', !thread.isRead && 'font-semibold')}>
                      {thread.subject || '(No Subject)'}
                    </h3>
                    {thread.hasAttachments && (
                      <Paperclip className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground truncate">
                    {from.name} - {latestEmail.preview || ''}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {thread.lastDate
                      ? formatDistanceToNow(thread.lastDate, { addSuffix: true })
                      : ''}
                  </span>
                  <ProcessingStatusBadge
                    status={processStatus}
                    error={latestEmail.ingestionLastError}
                    onErrorClick={onErrorClick}
                  />
                </div>
              </div>
              {thread.emails.length > 1 && (
                <div className="text-xs text-muted-foreground mt-1">
                  {numeral(thread.emails.length).format('0,0')} messages
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};

interface ProcessingStatusBadgeProps {
  status: ProcessingStatus;
  error?: string | null;
  onErrorClick: (error: string) => void;
}

const ProcessingStatusBadge = ({ status, error, onErrorClick }: ProcessingStatusBadgeProps) => {
  if (status === 'completed') {
    return (
      <Badge variant="outline" className="text-xs gap-1">
        <CheckCircle2 className="h-3 w-3 text-green-500" />
        Processed
      </Badge>
    );
  }

  if (status === 'processing') {
    return (
      <Badge variant="outline" className="text-xs gap-1">
        <Clock className="h-3 w-3 text-blue-500" />
        Processing
      </Badge>
    );
  }

  if (status === 'error') {
    return (
      <Badge
        variant="outline"
        className="text-xs gap-1 cursor-pointer hover:bg-destructive/10"
        onClick={(e) => {
          e.stopPropagation();
          if (error) onErrorClick(error);
        }}
      >
        <XCircle className="h-3 w-3 text-destructive" />
        Error
      </Badge>
    );
  }

  return (
    <Badge variant="outline" className="text-xs gap-1">
      <AlertCircle className="h-3 w-3 text-yellow-500" />
      Pending
    </Badge>
  );
};
