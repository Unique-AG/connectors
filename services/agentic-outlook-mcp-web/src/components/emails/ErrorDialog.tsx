import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface ErrorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  error: string | null;
}

export const ErrorDialog = ({ open, onOpenChange, error }: ErrorDialogProps) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Processing Error Details</DialogTitle>
          <DialogDescription>Error information from the email processing attempt</DialogDescription>
        </DialogHeader>
        <div className="mt-4">
          <pre className="bg-muted p-4 rounded-md overflow-x-auto text-xs whitespace-pre-wrap">
            {error || 'No error details available'}
          </pre>
        </div>
      </DialogContent>
    </Dialog>
  );
};

