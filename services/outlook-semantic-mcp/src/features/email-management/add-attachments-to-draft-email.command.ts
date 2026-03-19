import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span } from 'nestjs-otel';
import { type UniqueConfigNamespaced } from '~/config';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { parseAttachmentUri } from './parse-attachment-uri';
import { UploadInMemoryAttachmentCommand } from './email-attachments/upload-in-memory-attachment.command';
import { StreamUniqueAttachmentCommand } from './email-attachments/stream-unique-attachment.command';
import { AttachmentFailure, ResolvedUniqueIdentity } from './email-attachments/utils';

export interface AddAttachmentsInput {
  draftId: string;
  attachments: { fileName: string; data: string }[];
  chatId?: string;
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
    input: AddAttachmentsInput,
  ): Promise<AddAttachmentsResult> {
    const userProfileIdString = userProfileId.toString();
    const client = this.graphClientFactory.createClientForUser(userProfileIdString);
    const attachmentsFailed: AttachmentFailure[] = [];
    const profile = await this.getUserProfileQuery.run(userProfileId);

    this.logger.log({
      msg: 'Starting attachment upload',
      userProfileId: userProfileIdString,
      draftId: input.draftId,
      attachmentCount: input.attachments.length,
    });

    // This function is here because we cache the result.
    const resolveUniqueIdentity = this.createUniqueIdentityResolver(profile.email);

    for (const { data, fileName } of input.attachments) {
      try {
        const parsed = parseAttachmentUri(data);
        const logProps: Record<string, string | number> = {
          userProfileId: userProfileIdString,
          draftId: input.draftId,
          filename: fileName,
        };

        switch (parsed.type) {
          case 'unique': {
            const uniqueIdentity = await resolveUniqueIdentity();
            const result = await this.streamUniqueAttachmentCommand.run({
              client,
              draftId: input.draftId,
              fileInfo: {
                fileName,
                chatId: parsed.chatId || input.chatId,
                contentId: parsed.contentId,
              },
              uniqueIdentity,
              userProfileId: userProfileIdString,
            });
            if (result.status === 'failed') {
              attachmentsFailed.push(result.reason);
            }
            break;
          }
          case 'data':
            await this.uploadInMemoryAttachmentCommand.run({
              client,
              draftId: input.draftId,
              data: parsed.data,
              filename: fileName,
              totalSize: parsed.data.length,
              userProfileId: userProfileIdString,
            });
            logProps.fileSize = parsed.data.length;
            break;
        }
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        this.logger.warn({
          err,
          userProfileId: userProfileIdString,
          draftId: input.draftId,
          msg: 'Attachment failed',
        });
        attachmentsFailed.push({ fileName, reason });
      }
    }

    this.logger.log({
      msg: 'Attachment upload run complete',
      userProfileId: userProfileIdString,
      draftId: input.draftId,
      total: input.attachments.length,
      succeeded: input.attachments.length - attachmentsFailed.length,
      failed: attachmentsFailed.length,
    });

    return { attachmentsFailed };
  }

  private createUniqueIdentityResolver(email: string): IdentityResolver {
    const getIdentity = async (): Promise<ResolvedUniqueIdentity> => {
      if (cachedIdentity) {
        return cachedIdentity;
      }

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
