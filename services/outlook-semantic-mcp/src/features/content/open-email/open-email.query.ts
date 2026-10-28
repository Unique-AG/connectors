import { type UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, isNonNullish, map, pipe } from 'remeda';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { concatChunks } from '~/utils/concat-chunks';
import { convertDateTimeToTimezone } from '~/utils/convert-datetime-to-timezone';
import { Nullish } from '~/utils/nullish';

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
  isDraft: z.boolean().optional(),
  attachments: z
    .array(
      z.object({
        name: z.string(),
        size: z.number().optional(),
        isInline: z.boolean().optional(),
      }),
    )
    .default([]),
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
    isDraft: boolean;
    attachments?: { name: string; size?: number; isInline: boolean }[];
  };
  text: string;
  bodyContentType: 'text' | 'html';
  chunks?: string;
}

@Injectable()
export class OpenEmailQuery {
  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  @Span()
  public async run({
    userProfileId,
    id,
    mailbox,
    folderId,
    idIsImmutable,
    bodyContentType,
    uniqueContentId,
    chunkIds,
    outputTimeZone,
  }: {
    userProfileId: string;
    id: string;
    mailbox?: string;
    folderId?: string;
    idIsImmutable?: boolean;
    bodyContentType?: 'text' | 'html';
    uniqueContentId?: string;
    chunkIds?: string[];
    outputTimeZone?: string;
  }): Promise<OpenEmailResult> {
    const message = await this.readMessageFromMsGraph(
      userProfileId,
      id,
      mailbox,
      folderId,
      idIsImmutable,
      bodyContentType === 'html' ? 'html' : 'text',
      outputTimeZone,
    );
    if (!uniqueContentId) {
      return message;
    }
    return { ...message, chunks: await this.readRelevantChunks(uniqueContentId, chunkIds) };
  }

  private async readMessageFromMsGraph(
    userProfileId: string,
    messageId: string,
    mailbox?: string,
    folderId?: string,
    idIsImmutable?: boolean,
    bodyContentType: 'text' | 'html' = 'text',
    outputTimeZone?: string,
  ): Promise<OpenEmailResult> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const messagePath =
      mailbox && folderId
        ? `/users/${mailbox}/mailFolders/${folderId}/messages/${messageId}`
        : `/me/messages/${messageId}`;
    const immutableIdHeader = idIsImmutable ? ', IdType="ImmutableId"' : '';
    const raw = await client
      .api(messagePath)
      .header('Prefer', `outlook.body-content-type="${bodyContentType}"${immutableIdHeader}`)
      .select(
        'id,subject,body,from,toRecipients,ccRecipients,receivedDateTime,parentFolderId,webLink,hasAttachments,isDraft',
      )
      .expand('attachments($select=name,size,isInline)')
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
        receivedDateTime: convertDateTimeToTimezone(message.receivedDateTime, outputTimeZone),
        webLink: message.webLink,
        hasAttachments: message.hasAttachments === true,
        isDraft: message.isDraft === true,
        attachments: message.attachments.map(({ name, size, isInline }) => ({
          name,
          size,
          isInline: isInline === true,
        })),
      },
      text: message.body?.content ?? '',
      bodyContentType,
    };
  }

  private async readRelevantChunks(contentId: string, chunkIds?: string[]): Promise<string> {
    const emailData = await this.uniqueApi.content.getContentById({ contentId });
    const chunks = emailData.chunks ?? [];
    if (!chunkIds?.length) {
      return concatChunks(chunks);
    }
    const wanted = new Set(chunkIds);
    return concatChunks(chunks.filter((chunk) => wanted.has(chunk.id)));
  }
}
