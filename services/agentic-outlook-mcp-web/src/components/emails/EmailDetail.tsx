import { format } from 'date-fns';
import { Paperclip, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Email } from '@/lib/powersync/schema';
import { getProcessingStatus, parseFromField } from '@/types/email';

interface EmailDetailProps {
  emails: Email[];
  onReprocess: (emailId: string) => void;
}

export const EmailDetail = ({ emails, onReprocess }: EmailDetailProps) => {
  if (emails.length === 0) {
    return (
      <div className="h-full flex items-center justify-center bg-card">
        <p className="text-muted-foreground">Select an email to view details</p>
      </div>
    );
  }

  const latestEmail = emails[emails.length - 1];

  return (
    <div className="h-full bg-card overflow-y-auto">
      <div className="p-6 space-y-6">
        <div>
          <h1 className="text-2xl font-bold mb-4">{latestEmail.subject || '(No Subject)'}</h1>

          {emails.map((email, index) => {
            const from = parseFromField(email.from);
            const status = getProcessingStatus(email);

            return (
              <div key={email.id} className="mb-6">
                {index > 0 && <Separator className="my-4" />}

                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="font-medium">{from.name}</div>
                    <div className="text-sm text-muted-foreground">{from.email}</div>
                    {email.receivedAt && (
                      <div className="text-xs text-muted-foreground mt-1">
                        {format(new Date(email.receivedAt), 'PPpp')}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {email.hasAttachments && (
                      <Badge variant="outline" className="gap-1">
                        <Paperclip className="h-3 w-3" />
                        Attachments
                      </Badge>
                    )}
                    <Button
                      onClick={() => onReprocess(email.id)}
                      variant="outline"
                      size="sm"
                      className="gap-2"
                    >
                      <RefreshCw className="h-4 w-4" />
                      Re-Process
                    </Button>
                  </div>
                </div>

                {email.bodyHtml && (
                  <Card className="mb-4">
                    <CardHeader>
                      <CardTitle className="text-base">Original Content</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="prose prose-sm max-w-none dark:prose-invert">
                        <div dangerouslySetInnerHTML={{ __html: email.bodyHtml }} />
                      </div>
                    </CardContent>
                  </Card>
                )}

                {status === 'completed' && (
                  <>
                    {email.processedBody && (
                      <Card className="mb-4">
                        <CardHeader>
                          <CardTitle className="text-base">Processed Content</CardTitle>
                          <CardDescription>
                            {email.processedBody.length} characters
                          </CardDescription>
                        </CardHeader>
                        <CardContent>
                          <pre className="whitespace-pre-wrap text-sm bg-muted p-4 rounded-md overflow-x-auto">
                            {email.processedBody}
                          </pre>
                        </CardContent>
                      </Card>
                    )}

                    {email.translatedBody && (
                      <Card className="mb-4">
                        <CardHeader>
                          <CardTitle className="text-base">English Translation</CardTitle>
                          <CardDescription>
                            {email.translatedBody.length} characters
                          </CardDescription>
                        </CardHeader>
                        <CardContent>
                          <div className="space-y-2">
                            {email.translatedSubject && (
                              <div>
                                <div className="text-sm font-medium text-muted-foreground mb-1">
                                  Subject:
                                </div>
                                <div>{email.translatedSubject}</div>
                              </div>
                            )}
                            <div>
                              <div className="text-sm font-medium text-muted-foreground mb-1">
                                Body:
                              </div>
                              <div className="prose prose-sm max-w-none dark:prose-invert">
                                {email.translatedBody}
                              </div>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    )}

                    {email.summarizedBody && (
                      <Card className="mb-4">
                        <CardHeader>
                          <CardTitle className="text-base">Summary</CardTitle>
                          <CardDescription>
                            {email.summarizedBody.length} characters
                          </CardDescription>
                        </CardHeader>
                        <CardContent>
                          <p className="text-sm">{email.summarizedBody}</p>
                        </CardContent>
                      </Card>
                    )}
                  </>
                )}

                {status === 'error' && email.ingestionLastError && (
                  <Card className="mb-4 border-destructive">
                    <CardHeader>
                      <CardTitle className="text-base text-destructive">Processing Error</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-sm text-muted-foreground">{email.ingestionLastError}</p>
                    </CardContent>
                  </Card>
                )}
              </div>
            );
          })}

          {emails.length > 1 && latestEmail.threadSummary && (
            <Card className="mt-6">
              <CardHeader>
                <CardTitle className="text-base">Thread Summary</CardTitle>
                <CardDescription>{latestEmail.threadSummary.length} characters</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm">{latestEmail.threadSummary}</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
};

