import { type UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, isNonNullish, map, pipe, sortBy } from 'remeda';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { SearchBackend } from '../search/semantic-search-emails.query';

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

export interface OpenEmailResult {
  id: string;
  title: string | null;
  metadata: unknown;
  text: string;
}

@Injectable()
export class OpenEmailQuery {
  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  @Span()
  public async run(
    userProfileId: string,
    id: string,
    idType: SearchBackend,
  ): Promise<OpenEmailResult> {
    if (idType === SearchBackend.MsGraph) {
      return this.readMessageFromMsGraph(userProfileId, id);
    }
    return this.readMessageFromUnique(id);
  }

  private async readMessageFromMsGraph(
    userProfileId: string,
    messageId: string,
  ): Promise<OpenEmailResult> {
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
      text: message.body?.content ?? '',
    };
  }

  private async readMessageFromUnique(id: string): Promise<OpenEmailResult> {
    const emailData = await this.uniqueApi.content.getContentById({ contentId: id });
    return {
      id: emailData.id,
      title: emailData.title ?? null,
      metadata: emailData.metadata as unknown,
      text: pipe(
        emailData.chunks ?? [],
        sortBy((chunk) => chunk.order ?? 0),
        map((chunk) => chunk.text),
      ).join('\n'),
    };
  }
}
