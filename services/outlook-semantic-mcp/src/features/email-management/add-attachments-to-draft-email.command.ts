import { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared, Smeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span } from 'nestjs-otel';
import { type UniqueConfigNamespaced } from '~/config';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { StreamUniqueAttachmentCommand } from './email-attachments/stream-unique-attachment.command';
import { UploadInMemoryAttachmentCommand } from './email-attachments/upload-in-memory-attachment.command';
import {
  AttachmentFailure,
  AttachmentUploadResult,
  ResolvedUniqueIdentity,
} from './email-attachments/utils';
import { parseAttachmentUri } from './parse-attachment-uri';

export interface AddAttachmentsInput {
  draftId: string;
  attachments: { fileName: string; data: string }[];
}

export interface AddAttachmentsResult {
  attachmentsFailed: AttachmentFailure[];
}

type IdentityResolver = () => Promise<ResolvedUniqueIdentity>;

@Injectable()
export class AddAttachmentsToDraftEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @InjectUniqueApi() private readonly uniqueApiClient: UniqueApiClient,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly uploadInMemoryAttachmentCommand: UploadInMemoryAttachmentCommand,
    private readonly streamUniqueAttachmentCommand: StreamUniqueAttachmentCommand,
    private readonly configService: ConfigService<UniqueConfigNamespaced, true>,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    { draftId, attachments }: AddAttachmentsInput,
  ): Promise<AddAttachmentsResult> {
    const userProfileIdString = userProfileId.toString();
    const client = this.graphClientFactory.createClientForUser(userProfileIdString);
    const attachmentsFailed: AttachmentFailure[] = [];
    const profile = await this.getUserProfileQuery.run(userProfileId);

    this.logger.log({
      msg: 'Starting attachment upload',
      userProfileId: userProfileIdString,
      draftId,
      attachmentCount: attachments.length,
    });

    // This function is here because we cache the result.
    const resolveUniqueIdentity = this.createUniqueIdentityResolver(profile.email);

    for (const { data, fileName } of attachments) {
      try {
        const processResult = await this.processAttachment({
          data,
          fileName: createSmeared(fileName),
          userProfileId: userProfileIdString,
          client,
          draftId,
          resolveUniqueIdentity,
        });
        if (processResult.status === 'failed') {
          attachmentsFailed.push(processResult.reason);
        }
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        this.logger.warn({
          err,
          userProfileId: userProfileIdString,
          draftId,
          msg: 'Attachment failed',
        });
        attachmentsFailed.push({ fileName, reason });
      }
    }

    this.logger.log({
      msg: 'Attachment upload run complete',
      userProfileId: userProfileIdString,
      draftId,
      total: attachments.length,
      succeeded: attachments.length - attachmentsFailed.length,
      failed: attachmentsFailed.length,
    });

    return { attachmentsFailed };
  }

  private async processAttachment({
    userProfileId,
    client,
    draftId,
    data,
    resolveUniqueIdentity,
    fileName,
  }: {
    client: Client;
    fileName: Smeared;
    data: string;
    resolveUniqueIdentity: IdentityResolver;
    draftId: string;
    userProfileId: string;
  }): Promise<AttachmentUploadResult> {
    const parsed = parseAttachmentUri(data);

    switch (parsed.type) {
      case 'unique': {
        const uniqueIdentity = await resolveUniqueIdentity();
        const result = await this.streamUniqueAttachmentCommand.run({
          client,
          draftId,
          fileInfo: {
            fileName,
            contentId: parsed.contentId,
          },
          uniqueIdentity,
          userProfileId,
        });
        return result;
      }
      case 'data':
        await this.uploadInMemoryAttachmentCommand.run({
          client,
          userProfileId,
          draftId,
          data: parsed.data,
          fileName,
          mimeType: parsed.mimeType,
          totalSize: parsed.data.length,
        });
        return { status: 'success' };
      default:
        return {
          status: 'failed',
          reason: { fileName: fileName.value, reason: 'Unrecognised attachment type' },
        };
    }
  }

  private createUniqueIdentityResolver(email: string): IdentityResolver {
    const getIdentity = async (): Promise<ResolvedUniqueIdentity> => {
      const uniqueConfig = this.configService.get('unique', { infer: true });
      if (uniqueConfig.serviceAuthMode !== 'cluster_local') {
        return null;
      }
      try {
        const uniqueUser = await this.uniqueApiClient.users.findByEmail(email);
        if (uniqueUser) {
          return { userId: uniqueUser.id, companyId: uniqueUser.companyId };
        }
      } catch (err) {
        this.logger.error({ msg: 'Failed to resolve unique user identity', err });
      }
      return null;
    };

    let cachedIdentity: Promise<ResolvedUniqueIdentity>;
    return async (): Promise<ResolvedUniqueIdentity> => {
      if (cachedIdentity) {
        return cachedIdentity;
      }

      cachedIdentity = getIdentity();
      return cachedIdentity;
    };
  }
}
