import { format } from 'date-fns';
import { Paperclip, RefreshCw } from 'lucide-react';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Email } from '@/lib/powersync/schema';
import { getProcessingStatus, parseFromField } from '@/types/email';
import { SafeHtmlRenderer } from './SafeHtmlRenderer';

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

                <Accordion type="multiple" defaultValue={['original']} className="space-y-0">
                  {email.bodyHtml && (
                    <AccordionItem value="original" className="border-b">
                      <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
                        Original Content
                      </AccordionTrigger>
                      <AccordionContent className="pb-4">
                        <SafeHtmlRenderer html={email.bodyHtml} />
                      </AccordionContent>
                    </AccordionItem>
                  )}

                  {status === 'completed' && (
                    <>
                      {email.processedBody && (
                        <AccordionItem value="processed" className="border-b">
                          <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
                            Processed Content
                            <span className="ml-2 text-xs text-muted-foreground font-normal">
                              {email.processedBody.length} characters
                            </span>
                          </AccordionTrigger>
                          <AccordionContent className="pb-4">
                            <pre className="whitespace-pre-wrap text-sm bg-muted p-4 rounded-md overflow-x-auto">
                              {email.processedBody}
                            </pre>
                          </AccordionContent>
                        </AccordionItem>
                      )}

                      {email.translatedBody && (
                        <AccordionItem value="translated" className="border-b">
                          <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
                            English Translation
                            <span className="ml-2 text-xs text-muted-foreground font-normal">
                              {email.translatedBody.length} characters
                            </span>
                          </AccordionTrigger>
                          <AccordionContent className="pb-4">
                            <div className="space-y-3">
                              {email.translatedSubject && (
                                <div>
                                  <div className="text-xs font-medium text-muted-foreground mb-1">
                                    Subject:
                                  </div>
                                  <div className="text-sm">{email.translatedSubject}</div>
                                </div>
                              )}
                              <div>
                                <div className="text-xs font-medium text-muted-foreground mb-1">
                                  Body:
                                </div>
                                <div className="text-sm leading-relaxed">
                                  {email.translatedBody}
                                </div>
                              </div>
                            </div>
                          </AccordionContent>
                        </AccordionItem>
                      )}

                      {email.summarizedBody && (
                        <AccordionItem value="summary" className="border-b">
                          <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
                            Summary
                            <span className="ml-2 text-xs text-muted-foreground font-normal">
                              {email.summarizedBody.length} characters
                            </span>
                          </AccordionTrigger>
                          <AccordionContent className="pb-4">
                            <p className="text-sm leading-relaxed">{email.summarizedBody}</p>
                          </AccordionContent>
                        </AccordionItem>
                      )}
                    </>
                  )}

                  {status === 'error' && email.ingestionLastError && (
                    <AccordionItem value="error" className="border-b border-destructive/50">
                      <AccordionTrigger className="py-3 text-sm font-medium text-destructive hover:no-underline">
                        Processing Error
                      </AccordionTrigger>
                      <AccordionContent className="pb-4">
                        <p className="text-sm text-muted-foreground">{email.ingestionLastError}</p>
                      </AccordionContent>
                    </AccordionItem>
                  )}
                </Accordion>
              </div>
            );
          })}

          {emails.length > 1 && latestEmail.threadSummary && (
            <Accordion type="multiple" className="mt-6">
              <AccordionItem value="thread-summary" className="border-b">
                <AccordionTrigger className="py-3 text-sm font-medium hover:no-underline">
                  Thread Summary
                  <span className="ml-2 text-xs text-muted-foreground font-normal">
                    {latestEmail.threadSummary.length} characters
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-4">
                  <p className="text-sm leading-relaxed">{latestEmail.threadSummary}</p>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}
        </div>
      </div>
    </div>
  );
};
