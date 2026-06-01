import { Injectable } from '@nestjs/common';
import { isNullish } from 'remeda';
import { typeid } from 'typeid-js';
import { DirectoryType } from '~/db';
import {
  ListMailboxesAndDirectoriesQuery,
  UserDirectory,
} from '~/features/delegated-access/queries/list-mailboxes-and-directories.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { Nullish } from '~/utils/nullish';
import { resolveDirectoryIds } from './resolve-directory-ids.util';

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
  isOwn: boolean;
  directories: DirectoryInfo[];
}

const getRequestId = () => typeid('batch_request').toString();

const mapFoldersToDirectoryAccessFolders = (dirs: UserDirectory[]): DirectoryInfo[] => {
  return dirs.flatMap((dir): DirectoryInfo[] => {
    const children = mapFoldersToDirectoryAccessFolders(dir.children ?? []);
    if (!dir.canReadContent) {
      return children;
    }
    return [
      { displayName: dir.displayName, internalType: dir.internalType, providerDirectoryId: dir.id },
      ...children,
    ];
  });
};

@Injectable()
export class BuildMsGraphKqlBatchRequestsQuery {
  public constructor(
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
      ({ id, email, hasFullAccess, isOwn, folders }) => ({
        ownerId: id,
        ownerEmail: email,
        hasFullAccess,
        isOwn,
        directories: mapFoldersToDirectoryAccessFolders(folders),
      }),
    );

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

    return output;
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

    const isDelegated = !mailboxAccessInfo.isOwn;

    if (!query.directories) {
      if (mailboxAccessInfo.hasFullAccess) {
        // The user has full access we can search in all directories at once.
        output.requests.push({
          requestId: getRequestId(),
          mailbox: mailboxAccessInfo.ownerEmail,
          isDelegated,
          kqlQuery: query.kqlQuery,
          limit,
        });
        return;
      }

      // Since we do not have full access we have to search in every folder individually.
      for (const { providerDirectoryId } of mailboxAccessInfo.directories) {
        output.requests.push({
          requestId: getRequestId(),
          mailbox: mailboxAccessInfo.ownerEmail,
          isDelegated,
          folderId: providerDirectoryId,
          kqlQuery: query.kqlQuery,
          limit,
        });
      }
      return;
    }

    // Since we filter based on directories we do a fuzzy match on directory ids to resolve them properly for the
    // api calls.
    const resolved = resolveDirectoryIds(query.directories, mailboxAccessInfo.directories);
    for (const folderId of resolved.resolvedIds) {
      output.requests.push({
        requestId: getRequestId(),
        mailbox: mailboxAccessInfo.ownerEmail,
        isDelegated,
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
