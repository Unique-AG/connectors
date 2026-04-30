import { type UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, isNonNullish, map, pipe } from 'remeda';
import * as z from 'zod';
import { MessageMetadata } from '~/features/process-email/utils/get-metadata-from-message';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { concatChunks } from '~/utils/concat-chunks';
import { Nullish } from '~/utils/nullish';
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
  metadata: {
    from: Nullish<string>;
    toRecipients: Nullish<string[]>;
    ccRecipients: Nullish<string[]>;
    receivedDateTime: Nullish<string>;
    webLink: Nullish<string>;
    hasAttachments: boolean;
  };
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
        hasAttachments: message.hasAttachments === true,
      },
      text: message.body?.content ?? '',
    };
  }

  private async readMessageFromUnique(id: string): Promise<OpenEmailResult> {
    const emailData = await this.uniqueApi.content.getContentById({ contentId: id });
    const metadata = emailData.metadata as MessageMetadata | undefined;

    return {
      id: emailData.id,
      title: emailData.title ?? null,
      metadata: {
        from: metadata?.fromEmailAddress,
        toRecipients: metadata?.toRecipientsEmailAddresses,
        ccRecipients: metadata?.ccRecipientsEmailAddresses,
        receivedDateTime: metadata?.receivedDateTime,
        webLink: metadata?.webLink,
        hasAttachments: metadata?.hasAttachments === 'true',
      },
      text: concatChunks(emailData.chunks ?? []),
    };
  }
}
