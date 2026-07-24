import { createSmeared, smearEmail } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import {
  DRIZZLE,
  DrizzleDatabase,
  directories,
  SystemDirectoriesIgnoredForSync,
  SystemDirectoryType,
  UserProfile,
} from '~/db';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import {
  isNoDelegatesResult,
  MsGraphClientResolver,
} from '~/msgraph/ms-graph-client-resolver.service';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { GetUserProfileQuery } from '../user-utils/get-user-profile.query';
import { GraphOutlookDirectory, graphOutlookDirectory } from './microsoft-graph.dtos';

const MAP_SYSTEM_DIRECTORY_TO_MS_GRAPH_API_NAME: Record<SystemDirectoryType, string> = {
  Archive: 'archive',
  'Deleted Items': 'deleteditems',
  Drafts: 'drafts',
  Inbox: 'inbox',
  'Junk Email': 'junkemail',
  Outbox: 'outbox',
  'Sent Items': 'sentitems',
  'Conversation History': 'conversationhistory',
  'Recoverable Items Deletions': 'recoverableitemsdeletions',
  Clutter: 'clutter',
};

interface GraphDirectoryInfo {
  type: SystemDirectoryType;
  directoryInfo: GraphOutlookDirectory;
}

@Injectable()
export class SyncSystemDirectoriesForSubscriptionCommand {
  private logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly msGraphClientResolver: MsGraphClientResolver,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<void> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);

    traceEvent('Start system folders sync');
    const microsoftGraphDirectories = await this.msGraphClientResolver.run({
      userProfile,
      fn: ({ client }) => this.fetchMicrosoftSystemFolders(client, userProfile),
    });
    traceEvent('Finished reading microsoft graph system directories');

    if (isNoDelegatesResult(microsoftGraphDirectories)) {
      this.logger.warn({
        userProfileId: userProfile.id,
        userEmail: smearEmail(createSmeared(userProfile.email)),
        msg: `No delegates found for shared mailbox, skipping directory sync`,
      });
      return;
    }

    await this.syncSystemFolders({
      microsoftGraphDirectories,
      userProfile,
    });
    traceEvent('System folders sync finished');
  }

  @Span()
  private async fetchMicrosoftSystemFolders(
    client: Client,
    userProfile: NonNullishProps<UserProfile, 'email'>,
  ): Promise<GraphDirectoryInfo[]> {
    traceAttrs({ userProfileId: userProfile.id });

    traceEvent('Start fetching system directories from microsoft graph');
    const baseUrl =
      userProfile.source === 'shared-mailbox'
        ? `users/${userProfile.email}/mailFolders`
        : `me/mailFolders`;
    const microsoftGraphDirectories: GraphDirectoryInfo[] = [];
    for (const [directoryType, apiName] of Object.entries(
      MAP_SYSTEM_DIRECTORY_TO_MS_GRAPH_API_NAME,
    )) {
      const directoryResponse = await client.api(`${baseUrl}/${apiName}`).get();
      microsoftGraphDirectories.push({
        type: directoryType as SystemDirectoryType,
        directoryInfo: graphOutlookDirectory.parse(directoryResponse),
      });
    }
    traceEvent('Finish fetching system directories from microsoft graph');
    return microsoftGraphDirectories;
  }

  @Span()
  private async syncSystemFolders({
    microsoftGraphDirectories,
    userProfile,
  }: {
    userProfile: UserProfile;
    microsoftGraphDirectories: GraphDirectoryInfo[];
  }): Promise<void> {
    await this.db
      .insert(directories)
      .values(
        microsoftGraphDirectories.map(({ directoryInfo, type }) => {
          return {
            userProfileId: userProfile.id,
            providerDirectoryId: directoryInfo.id,
            internalType: type,
            displayName: directoryInfo.displayName,
            parentId: null,
            ignoreForSync: SystemDirectoriesIgnoredForSync.includes(type),
          };
        }),
      )
      .onConflictDoUpdate({
        target: [directories.userProfileId, directories.providerDirectoryId],
        set: {
          ignoreForSync: sql.raw(`excluded.${directories.ignoreForSync.name}`),
          internalType: sql.raw(`excluded.${directories.internalType.name}`),
          parentId: sql.raw(`excluded.${directories.parentId.name}`),
          displayName: sql.raw(`excluded.${directories.displayName.name}`),
        },
      })
      .execute();
  }
}
