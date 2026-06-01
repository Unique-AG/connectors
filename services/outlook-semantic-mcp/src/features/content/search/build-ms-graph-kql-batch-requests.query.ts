import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { typeid } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, directories } from '~/db';
import { GetDelegatedAccessQuery } from '~/features/delegated-access/queries/get-delegates-access.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { resolveDirectoryIds } from './resolve-directory-ids.util';

export interface QueryInput {
  kqlQuery: string;
  limit?: number;
  mailbox?: string | null | undefined;
  directories?: string[];
}

export interface GraphBatchRequest {
  requestId: string;
  mailbox: string;
  isDelegated: boolean;
  kqlQuery: string;
  limit: number;
  folderId?: string;
}

@Injectable()
export class BuildMsGraphKqlBatchRequestsQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly getDelegatedAccessQuery: GetDelegatedAccessQuery,
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
    const allDelegatedAccesses = await this.getDelegatedAccessQuery.run(userProfile.id);
    const fullDelegated = allDelegatedAccesses.filter((a) => a.hasFullDelegatedAccess);
    const directoryOnly = allDelegatedAccesses.filter((a) => !a.hasFullDelegatedAccess);

    const requests: GraphBatchRequest[] = [];
    const skippedFolders: Array<{ mailbox: string; folder: string }> = [];

    const getRequestId = () => typeid('batch_request').toString();

    const directoriesCache = new Map<string, ReturnType<typeof this.fetchDirectoriesForUser>>();
    const fetchDirs = (userId: string) => {
      if (!directoriesCache.has(userId)) {
        directoriesCache.set(userId, this.fetchDirectoriesForUser(userId));
      }
      return directoriesCache.get(userId)!;
    };

    for (const query of queries) {
      const limit = query.limit ?? 100;
      const { mailbox } = query;

      if (mailbox) {
        if (mailbox === userProfile.email) {
          if (query.directories) {
            const resolved = this.resolveForMailbox(
              query.directories,
              await fetchDirs(userProfile.id),
            );
            for (const folderId of resolved.resolvedIds) {
              requests.push({
                requestId: getRequestId(),
                mailbox: userProfile.email,
                isDelegated: false,
                kqlQuery: query.kqlQuery,
                limit,
                folderId,
              });
            }
            for (const folder of resolved.unrecognized) {
              skippedFolders.push({ mailbox, folder });
            }
          } else {
            requests.push({
              requestId: getRequestId(),
              mailbox: userProfile.email,
              isDelegated: false,
              kqlQuery: query.kqlQuery,
              limit,
            });
          }
          continue;
        }

        const fullAccess = fullDelegated.find((a) => a.ownerUserEmail === mailbox);
        if (fullAccess) {
          if (query.directories) {
            const resolved = this.resolveForMailbox(
              query.directories,
              await fetchDirs(fullAccess.ownerUserId),
            );
            for (const folderId of resolved.resolvedIds) {
              requests.push({
                requestId: getRequestId(),
                mailbox,
                isDelegated: true,
                kqlQuery: query.kqlQuery,
                limit,
                folderId,
              });
            }
            for (const folder of resolved.unrecognized) {
              skippedFolders.push({ mailbox, folder });
            }
          } else {
            requests.push({
              requestId: getRequestId(),
              mailbox,
              isDelegated: true,
              kqlQuery: query.kqlQuery,
              limit,
            });
          }
          continue;
        }

        const dirOnlyAccess = directoryOnly.find((a) => a.ownerUserEmail === mailbox);
        if (dirOnlyAccess) {
          if (query.directories) {
            const resolved = await this.resolveForDirectoryOnlyMailbox(
              dirOnlyAccess.ownerUserId,
              dirOnlyAccess.msGraphDirectoryIds,
              query.directories,
              fetchDirs,
            );
            for (const folderId of resolved.resolvedIds) {
              requests.push({
                requestId: getRequestId(),
                mailbox,
                isDelegated: true,
                kqlQuery: query.kqlQuery,
                limit,
                folderId,
              });
            }
            for (const folder of resolved.unrecognized) {
              skippedFolders.push({ mailbox, folder });
            }
          } else {
            for (const folderId of dirOnlyAccess.msGraphDirectoryIds) {
              requests.push({
                requestId: getRequestId(),
                mailbox,
                isDelegated: true,
                kqlQuery: query.kqlQuery,
                limit,
                folderId,
              });
            }
          }
          continue;
        }

        // mailbox not accessible — skip
        continue;
      }

      // No mailbox specified: fan out to own + all delegated
      if (query.directories) {
        const ownResolved = this.resolveForMailbox(query.directories, await fetchDirs(userProfile.id));
        for (const folderId of ownResolved.resolvedIds) {
          requests.push({
            requestId: getRequestId(),
            mailbox: userProfile.email,
            isDelegated: false,
            kqlQuery: query.kqlQuery,
            limit,
            folderId,
          });
        }
        for (const folder of ownResolved.unrecognized) {
          skippedFolders.push({ mailbox: userProfile.email, folder });
        }

        for (const access of fullDelegated.slice(0, 25)) {
          const resolved = this.resolveForMailbox(
            query.directories,
            await fetchDirs(access.ownerUserId),
          );
          for (const folderId of resolved.resolvedIds) {
            requests.push({
              requestId: getRequestId(),
              mailbox: access.ownerUserEmail,
              isDelegated: true,
              kqlQuery: query.kqlQuery,
              limit,
              folderId,
            });
          }
          for (const folder of resolved.unrecognized) {
            skippedFolders.push({ mailbox: access.ownerUserEmail, folder });
          }
        }

        for (const access of directoryOnly) {
          const resolved = await this.resolveForDirectoryOnlyMailbox(
            access.ownerUserId,
            access.msGraphDirectoryIds,
            query.directories,
            fetchDirs,
          );
          for (const folderId of resolved.resolvedIds) {
            requests.push({
              requestId: getRequestId(),
              mailbox: access.ownerUserEmail,
              isDelegated: true,
              kqlQuery: query.kqlQuery,
              limit,
              folderId,
            });
          }
          for (const folder of resolved.unrecognized) {
            skippedFolders.push({ mailbox: access.ownerUserEmail, folder });
          }
        }
      } else {
        requests.push({
          requestId: getRequestId(),
          mailbox: userProfile.email,
          isDelegated: false,
          kqlQuery: query.kqlQuery,
          limit,
        });

        for (const access of fullDelegated.slice(0, 25)) {
          requests.push({
            requestId: getRequestId(),
            mailbox: access.ownerUserEmail,
            isDelegated: true,
            kqlQuery: query.kqlQuery,
            limit,
          });
        }

        for (const access of directoryOnly) {
          for (const folderId of access.msGraphDirectoryIds) {
            requests.push({
              requestId: getRequestId(),
              mailbox: access.ownerUserEmail,
              isDelegated: true,
              kqlQuery: query.kqlQuery,
              limit,
              folderId,
            });
          }
        }
      }
    }

    return { requests, skippedFolders };
  }

  private async fetchDirectoriesForUser(userProfileId: string) {
    return this.db
      .select({
        providerDirectoryId: directories.providerDirectoryId,
        displayName: directories.displayName,
        internalType: directories.internalType,
      })
      .from(directories)
      .where(
        and(
          eq(directories.userProfileId, userProfileId),
          eq(directories.ignoreForSync, false),
        ),
      );
  }

  private resolveForMailbox(
    inputDirectories: string[],
    fetchedDirs: Awaited<ReturnType<typeof this.fetchDirectoriesForUser>>,
  ) {
    return resolveDirectoryIds(inputDirectories, fetchedDirs);
  }

  private async resolveForDirectoryOnlyMailbox(
    ownerUserId: string,
    msGraphDirectoryIds: string[],
    inputDirectories: string[],
    fetchDirs: (userId: string) => ReturnType<typeof this.fetchDirectoriesForUser>,
  ) {
    const fetchedDirs = await fetchDirs(ownerUserId);
    const accessibleDirs = fetchedDirs.filter((d) =>
      msGraphDirectoryIds.includes(d.providerDirectoryId),
    );
    return resolveDirectoryIds(inputDirectories, accessibleDirs);
  }
}
