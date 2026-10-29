import { type UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, isNonNullish, map, pipe } from 'remeda';
import * as z from 'zod';
import { encodeGraphItemIdForUrlPath } from '~/msgraph/encode-graph-item-id-for-url-path';
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
        name: z.string().nullish(),
        size: z.number().nullish(),
        isInline: z.boolean().nullish(),
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
  private readonly logger = new Logger(this.constructor.name);

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
    try {
      const chunks = await this.readRelevantChunks(uniqueContentId, chunkIds);
      return chunks === undefined ? message : { ...message, chunks };
    } catch (err) {
      this.logger.warn({
        msg: 'Failed to read matched chunks from Unique; returning the Graph body without them',
        uniqueContentId,
        err,
      });
      return message;
    }
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
    const encodedMessageId = encodeGraphItemIdForUrlPath(messageId);
    const messagePath = !mailbox
      ? `/me/messages/${encodedMessageId}`
      : folderId
        ? `/users/${mailbox}/mailFolders/${encodeGraphItemIdForUrlPath(folderId)}/messages/${encodedMessageId}`
        : `/users/${mailbox}/messages/${encodedMessageId}`;
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
        attachments: message.attachments.flatMap(({ name, size, isInline }) =>
          name ? [{ name, size: size ?? undefined, isInline: isInline === true }] : [],
        ),
      },
      text: message.body?.content ?? '',
      bodyContentType,
    };
  }

  private async readRelevantChunks(
    contentId: string,
    chunkIds?: string[],
  ): Promise<string | undefined> {
    const emailData = await this.uniqueApi.content.getContentById({ contentId });
    const chunks = emailData.chunks ?? [];
    if (!chunkIds?.length) {
      return concatChunks(chunks);
    }
    const wanted = new Set(chunkIds);
    const matched = chunks.filter((chunk) => wanted.has(chunk.id));
    if (!matched.length) {
      // The email was ingested again after the search, so its chunks have new ids.
      this.logger.warn({
        msg: 'None of the matched chunks are on the ingested email anymore; returning the Graph body without them',
        uniqueContentId: contentId,
      });
      return undefined;
    }
    return concatChunks(matched);
  }
}
