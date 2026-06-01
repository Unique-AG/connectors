import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { typeid } from 'typeid-js';
import { DRIZZLE, DirectoryType, DrizzleDatabase, directories } from '~/db';
import { GetDelegatedAccessQuery } from '~/features/delegated-access/queries/get-delegates-access.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { resolveDirectoryIds } from './resolve-directory-ids.util';
import { Nullish } from '~/utils/nullish';
import { isNullish } from 'remeda';
import {
  ListMailboxesAndDirectoriesQuery,
  UserDirectory,
} from '~/features/user-utils/list-mailboxes-and-directories.query';

export interface QueryInput {
  kqlQuery: string;
  limit?: number;
  mailbox?: string | null | undefined;
  directories?: string[];
}

interface DirectoryInfo {
  providerDirectoryId: string;
  displayName: string;
  internalType: DirectoryType;
}

export interface GraphBatchRequest {
  requestId: string;
  mailbox: string;
  isDelegated: boolean;
  kqlQuery: string;
  limit: number;
  folderId?: string;
}

interface MailboxAccessInfo {
  ownerId: string;
  ownerEmail: string;
  hasFullAccess: boolean;
  directories: DirectoryInfo[];
}

const getRequestId = () => typeid('batch_request').toString();

const flattenFolders = (dirs: UserDirectory[]): DirectoryInfo[] => {
  return dirs.flatMap((dir): DirectoryInfo[] => {
    return [
      { displayName: dir.displayName, internalType: dir.internalType, providerDirectoryId: dir.id },
      ...flattenFolders(dir.children ?? []).flatMap(),
    ];
  });
};

@Injectable()
export class BuildMsGraphKqlBatchRequestsQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly listMailboxesAndDirectoriesQuery: ListMailboxesAndDirectoriesQuery,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  public async run(
    userProfileId: UserProfileTypeID,
    queries: QueryInput[],
  ): Promise<{
    requests: GraphBatchRequest[];
    skippedFolders: Array<{ mailbox: string; folder: string }>;
  }> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const accessibleMailboxes = await this.listMailboxesAndDirectoriesQuery.run(userProfile.id);
    const mailboxAccessInfos: MailboxAccessInfo[] = accessibleMailboxes.map(
      ({ ownerId, email, hasFullAccess, folders }) => {
        const foldersFlat = flattenFolders(folders);

        return {
          ownerId,
          ownerEmail: email,
          hasFullAccess,
          directories: foldersFlat,
        };
      },
    );

    const requests: GraphBatchRequest[] = [];
    const skippedFolders: Array<{ mailbox: string; folder: string }> = [];
    const output: {
      requests: GraphBatchRequest[];
      skippedFolders: { mailbox: string; folder: string }[];
    } = {
      requests: [],
      skippedFolders: [],
    };

    for (const query of queries) {
      const { mailbox } = query;

      if (mailbox) {
        const mailboxAccessInfo = mailboxAccessInfos.find((item) => item.ownerEmail === mailbox);
        this.addQueryToGraphBatchRequests({
          output,
          query,
          mailboxAccessInfo,
        });
        continue;
      }

      for (const mailboxAccessInfo of mailboxAccessInfos) {
        this.addQueryToGraphBatchRequests({
          output,
          query,
          mailboxAccessInfo,
        });
      }
    }

    return { requests, skippedFolders };
  }

  private addQueryToGraphBatchRequests({
    query,
    mailboxAccessInfo,
    output,
  }: {
    query: QueryInput;
    mailboxAccessInfo: Nullish<MailboxAccessInfo>;
    output: {
      requests: GraphBatchRequest[];
      skippedFolders: { mailbox: string; folder: string }[];
    };
  }): void {
    const limit = query.limit ?? 100;
    if (isNullish(mailboxAccessInfo)) {
      return;
    }

    if (!query.directories) {
      if (mailboxAccessInfo.hasFullAccess) {
        output.requests.push({
          requestId: getRequestId(),
          mailbox: mailboxAccessInfo.ownerEmail,
          isDelegated: false,
          kqlQuery: query.kqlQuery,
          limit,
        });
        return;
      }

      for (const { providerDirectoryId } of mailboxAccessInfo.directories) {
        output.requests.push({
          requestId: getRequestId(),
          mailbox: mailboxAccessInfo.ownerEmail,
          isDelegated: false,
          folderId: providerDirectoryId,
          kqlQuery: query.kqlQuery,
          limit,
        });
      }
      return;
    }

    const resolved = resolveDirectoryIds(query.directories, mailboxAccessInfo.directories);
    for (const folderId of resolved.resolvedIds) {
      output.requests.push({
        requestId: getRequestId(),
        mailbox: mailboxAccessInfo.ownerEmail,
        isDelegated: false,
        kqlQuery: query.kqlQuery,
        limit,
        folderId,
      });
    }
    for (const folder of resolved.unrecognized) {
      output.skippedFolders.push({ mailbox: mailboxAccessInfo.ownerEmail, folder });
    }
  }
}
