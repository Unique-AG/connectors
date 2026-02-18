import { Inject, Injectable } from '@nestjs/common';
import { sql } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import {
  DRIZZLE,
  DrizzleDatabase,
  directories,
  SystemDirectoriesIgnoredForSync,
  SystemDirectoryType,
  UserProfile,
} from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
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
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly trace: TraceService,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(userProfileTypeId: UserProfileTypeID): Promise<void> {
    const span = this.trace.getSpan();
    const userProfile = await this.getUserProfileQuery.run(userProfileTypeId);

    span?.addEvent(`Start system folders sync`);
    const microsoftGraphDirectories = await this.fetchMicrosoftSystemFolders(userProfile.id);
    span?.addEvent(`Finished reading microsoft graph system directories`);

    await this.syncSystemFolders({
      microsoftGraphDirectories,
      userProfile,
    });
    span?.addEvent(`System folders sync finished`);
  }

  @Span()
  private async fetchMicrosoftSystemFolders(userProfileId: string): Promise<GraphDirectoryInfo[]> {
    const span = this.trace.getSpan();
    span?.setAttribute('user_profile_id', userProfileId.toString());

    span?.addEvent(`Start fetching system directories from microsoft graph`);
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const microsoftGraphDirectories: GraphDirectoryInfo[] = [];
    for (const [directoryType, apiName] of Object.entries(
      MAP_SYSTEM_DIRECTORY_TO_MS_GRAPH_API_NAME,
    )) {
      const directoryResponse = await client.api(`me/mailFolders/${apiName}`).get();
      microsoftGraphDirectories.push({
        type: directoryType as SystemDirectoryType,
        directoryInfo: graphOutlookDirectory.parse(directoryResponse),
      });
    }
    span?.addEvent(`Finish fetching system directories from microsoft graph`);
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
      });
  }
}
