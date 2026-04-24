import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

interface OpenEmailResult {
  id: string;
  title: string | null;
  metadata: {
    from: string | undefined;
    toRecipients: string[] | undefined;
    ccRecipients: string[] | undefined;
    receivedDateTime: string | undefined;
    webLink: string | undefined;
    hasAttachments: boolean | undefined;
  };
  chunks: Array<{
    id: string;
    startPage: null;
    endPage: null;
    order: number;
    text: string;
  }>;
}

@Injectable()
export class GraphOpenEmailQuery {
  constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  async run(userProfileId: string, messageId: string): Promise<OpenEmailResult> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const message = await client
      .api(`/me/messages/${messageId}`)
      .select(
        'id,subject,body,from,toRecipients,ccRecipients,receivedDateTime,parentFolderId,webLink,hasAttachments',
      )
      .get();

    return {
      id: message.id,
      title: message.subject,
      metadata: {
        from: message.from?.emailAddress?.address,
        toRecipients: message.toRecipients
          ?.map((r: { emailAddress?: { address?: string } }) => r.emailAddress?.address)
          .filter((a): a is string => a !== undefined),
        ccRecipients: message.ccRecipients
          ?.map((r: { emailAddress?: { address?: string } }) => r.emailAddress?.address)
          .filter((a): a is string => a !== undefined),
        receivedDateTime: message.receivedDateTime,
        webLink: message.webLink,
        hasAttachments: message.hasAttachments,
      },
      chunks: [
        {
          id: message.id,
          startPage: null,
          endPage: null,
          order: 0,
          text: message.body?.content ?? '',
        },
      ],
    };
  }
}
