import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, isNonNullish, map, pipe } from 'remeda';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

const recipientSchema = z.object({
  emailAddress: z.object({ address: z.string() }).optional(),
});

const graphMessageSchema = z.object({
  id: z.string(),
  subject: z.string().nullable().optional(),
  body: z.object({ content: z.string().optional() }).optional(),
  from: z.object({ emailAddress: z.object({ address: z.string() }).optional() }).optional(),
  toRecipients: z.array(recipientSchema).default([]),
  ccRecipients: z.array(recipientSchema).default([]),
  receivedDateTime: z.string().optional(),
  webLink: z.string().optional(),
  hasAttachments: z.boolean().optional(),
});

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
  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(userProfileId: string, messageId: string): Promise<OpenEmailResult> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const raw = await client
      .api(`/me/messages/${messageId}`)
      .select(
        'id,subject,body,from,toRecipients,ccRecipients,receivedDateTime,parentFolderId,webLink,hasAttachments',
      )
      .get();

    const message = graphMessageSchema.parse(raw);

    return {
      id: message.id,
      title: message.subject ?? null,
      metadata: {
        from: message.from?.emailAddress?.address,
        toRecipients: pipe(
          message.toRecipients,
          map((item) => item.emailAddress?.address),
          filter(isNonNullish),
        ),
        ccRecipients: pipe(
          message.ccRecipients,
          map((item) => item.emailAddress?.address),
          filter(isNonNullish),
        ),
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
