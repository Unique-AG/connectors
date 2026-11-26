import { type UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, isNonNullish, map, pipe } from 'remeda';
import * as z from 'zod';
import { BuildWebLinksCommand } from '~/features/graph-utils/build-web-links.command';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { graphMessagePath } from '~/msgraph/graph-message-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { concatChunks } from '~/utils/concat-chunks';
import { convertDateTimeToTimezone } from '~/utils/convert-datetime-to-timezone';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { subjectOrFallback } from '~/utils/no-subject';
import { Nullish } from '~/utils/nullish';
import { SensitivityFilter, SensitivityJudgement, SensitivityVerdict } from '../sensitivity-filter';

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
    // Graph sends null, not [], for a message expanded with no attachments.
    .nullish()
    .transform((attachments) => attachments ?? []),
  'attachments@odata.nextLink': z.string().optional(),
  singleValueExtendedProperties: z.unknown().optional(),
});

export interface OpenEmailResult {
  id: string;
  title: string;
  webLink: string | null;
  metadata: {
    from: Nullish<string>;
    toRecipients: Nullish<string[]>;
    ccRecipients: Nullish<string[]>;
    receivedDateTime: Nullish<string>;
    hasAttachments: boolean;
    isDraft: boolean;
    attachments?: { name: string; size?: number; isInline: boolean }[];
  };
  text: string;
  bodyContentType: 'text' | 'html';
  chunks?: string;
}

// A message the sensitivity filter withholds. Its content is not returned to the agent.
export interface WithheldEmail {
  withheld: Exclude<SensitivityJudgement, { verdict: SensitivityVerdict.Allowed }>;
}

@Injectable()
export class OpenEmailQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly buildWebLinksCommand: BuildWebLinksCommand,
    private readonly sensitivityFilter: SensitivityFilter,
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
    userProfileId: UserProfileTypeID;
    id: string;
    mailbox?: string;
    folderId?: string;
    idIsImmutable?: boolean;
    bodyContentType?: 'text' | 'html';
    uniqueContentId?: string;
    chunkIds?: string[];
    outputTimeZone?: string;
  }): Promise<OpenEmailResult | WithheldEmail> {
    const message = await this.readMessageFromMsGraph(
      userProfileId,
      id,
      mailbox,
      folderId,
      idIsImmutable,
      bodyContentType === 'html' ? 'html' : 'text',
      outputTimeZone,
    );
    if ('withheld' in message || !uniqueContentId) {
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
    userProfileId: UserProfileTypeID,
    messageId: string,
    mailbox?: string,
    folderId?: string,
    idIsImmutable?: boolean,
    bodyContentType: 'text' | 'html' = 'text',
    outputTimeZone?: string,
  ): Promise<OpenEmailResult | WithheldEmail> {
    const client = this.graphClientFactory.createClientForUser(userProfileId.toString());
    const messagePath = graphMessagePath({ messageId, mailbox, folderId });
    const immutableIdHeader = idIsImmutable ? ', IdType="ImmutableId"' : '';
    const raw = await client
      .api(messagePath)
      .header('Prefer', `outlook.body-content-type="${bodyContentType}"${immutableIdHeader}`)
      .select(
        'id,subject,body,from,toRecipients,ccRecipients,receivedDateTime,parentFolderId,webLink,hasAttachments,isDraft',
      )
      .expand(
        [
          'attachments($select=name,size,isInline)',
          ...(this.sensitivityFilter.isActive ? [this.sensitivityFilter.expand] : []),
        ].join(','),
      )
      .get();

    const message = graphMessageSchema.parse(raw);
    const sensitivity = this.sensitivityFilter.judge(message.singleValueExtendedProperties);
    if (sensitivity.verdict !== SensitivityVerdict.Allowed) {
      if (sensitivity.verdict === SensitivityVerdict.Unreadable) {
        this.logger.warn({
          msg: 'Withheld a message whose sensitivity could not be read',
          userProfileId: userProfileId.toString(),
        });
      }
      return { withheld: sensitivity };
    }
    if (message['attachments@odata.nextLink'] !== undefined) {
      this.logger.warn({
        msg: 'Microsoft Graph returned only part of the attachments of the message',
        userProfileId: userProfileId.toString(),
      });
    }

    return {
      id: message.id,
      title: subjectOrFallback(message.subject),
      webLink: await this.buildWebLink({
        userProfileId,
        messageId: message.id,
        mailbox,
        isImmutable: idIsImmutable === true,
        graphWebLink: message.webLink,
      }),
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

  // See BuildWebLinksCommand for why the Graph webLink cannot be used directly for delegated mailboxes.
  private async buildWebLink({
    userProfileId,
    messageId,
    mailbox,
    isImmutable,
    graphWebLink,
  }: {
    userProfileId: UserProfileTypeID;
    messageId: string;
    mailbox: string | undefined;
    isImmutable: boolean;
    graphWebLink: string | undefined;
  }): Promise<string | null> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const messageMailbox = mailbox ?? userProfile.email;
    const webLinks = await this.buildWebLinksCommand.run({
      userProfileId: userProfile.id,
      userProfileEmail: userProfile.email,
      ids: [{ id: messageId, isImmutable, mailbox: messageMailbox, webLink: graphWebLink ?? '' }],
    });
    return webLinks.get(messageMailbox, messageId) || null;
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
