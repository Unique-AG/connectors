import { createSmeared, smearPath } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNullish, unique } from 'remeda';
import {
  DRIZZLE,
  type DrizzleDatabase,
  delegatedAccessAccounts,
  delegatedAccessDirectories,
  directories,
  userProfiles,
} from '~/db';

interface DirectoryNode {
  id: string;
  displayName: string;
  parentId: string | null;
  providerDirectoryId: string;
}

export interface UserDirectory {
  id: string;
  displayName: string;
  canReadContent: boolean;
  children: UserDirectory[];
}

export interface UserMailbox {
  email: string | null;
  displayName: string | null;
  isOwn: boolean;
  folders: UserDirectory[];
}

@Injectable()
export class ListMailboxesAndDirectoriesQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Span()
  public async run(userProfileId: string): Promise<UserMailbox[]> {
    // Fetch own user profile for identity info
    const ownProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });

    // Fetch own directories
    const ownDirectories = await this.db.query.directories.findMany({
      where: and(
        eq(directories.userProfileId, userProfileId),
        // We filter out directories ignored for sync because they cannot be used in searches.
        eq(directories.ignoreForSync, false),
      ),
    });

    const { directoryTree: ownTree, paths: ownPaths } = this.buildTree({
      allDirectories: ownDirectories,
      isReadable: () => true,
    });
    this.logger.debug({
      msg: `Returned Directories: ${ownPaths.length}`,
      userProfileId,
      directories: ownPaths.map((item) => smearPath(createSmeared(item))).join('\r\n'),
    });

    const ownMailbox: UserMailbox = {
      email: ownProfile?.email ?? null,
      displayName: ownProfile?.displayName ?? null,
      isOwn: true,
      folders: ownTree,
    };

    // const delegatedDirectoryRows = [...directoryLevelRows, ...fullAccessRows];

    // if (delegatedDirectoryRows.length === 0) {
    //   return [ownMailbox];
    // }

    // const ownerDirs = new Map<
    //   string,
    //   { email: string | null; displayName: string | null; dirs: DirectoryNode[] }
    // >();
    // for (const row of delegatedDirectoryRows) {
    //   let directoriesRef = ownerDirs.get(row.ownerUserId)?.dirs;
    //   if (isNullish(directoriesRef)) {
    //     directoriesRef = [];
    //     ownerDirs.set(row.ownerUserId, {
    //       email: row.ownerEmail ?? null,
    //       displayName: row.ownerDisplayName ?? null,
    //       dirs: directoriesRef,
    //     });
    //   }

    //   directoriesRef.push({
    //     id: row.dirId,
    //     displayName: row.dirDisplayName,
    //     parentId: row.dirParentId,
    //     providerDirectoryId: row.dirProviderDirectoryId,
    //   });
    // }

    const mailbosesWithSharedFolders = await this.getMailboxesWithSharedFolders(userProfileId);
    const mailboxesWithFullAccess = await this.getMailboxesWithFullAccess(userProfileId);
    // const delegatedMailboxes: UserMailbox[] = [
    //   ...mailboxesWithFullAccess,
    //   ...mailbosesWithSharedFolders,
    // ];
    // for (const [, ownerInfo] of ownerDirs) {
    //   const { directoryTree } = this.buildTree(ownerInfo.dirs);
    //   delegatedMailboxes.push({
    //     email: ownerInfo.email,
    //     displayName: ownerInfo.displayName,
    //     isOwn: false,
    //     folders: directoryTree,
    //   });
    // }

    return [ownMailbox, ...mailboxesWithFullAccess, ...mailbosesWithSharedFolders];
  }

  private async getMailboxesWithSharedFolders(userProfileId: string): Promise<UserMailbox[]> {
    const dirId = sql.identifier(directories.id.name);
    const dirDisplayName = sql.identifier(directories.displayName.name);
    const dirParentId = sql.identifier(directories.parentId.name);
    const dirProviderDirectoryId = sql.identifier(directories.providerDirectoryId.name);
    const dirUserProfileId = sql.identifier(directories.userProfileId.name);

    const result = await this.db.execute<DirectoryInfoRowWithReadable>(sql`
      WITH RECURSIVE
      readable_seed AS (
        SELECT DISTINCT ${directories.id} AS dir_id
        FROM ${delegatedAccessAccounts}
        INNER JOIN ${delegatedAccessDirectories}
          ON ${delegatedAccessDirectories.accountsId} = ${delegatedAccessAccounts.id}
        INNER JOIN ${directories}
          ON ${directories.userProfileId} = ${delegatedAccessAccounts.ownerUserId}
          AND ${directories.providerDirectoryId} = ${delegatedAccessDirectories.directoryId}
          AND ${directories.ignoreForSync} = false
        WHERE ${delegatedAccessAccounts.delegateUserId} = ${userProfileId}
          AND ${delegatedAccessAccounts.hasFullDelegatedAccess} = false
      ),
      dir_tree AS (
        SELECT ${directories.id}, ${directories.displayName}, ${directories.parentId}, ${directories.providerDirectoryId}, ${directories.userProfileId}
        FROM ${directories}
        WHERE ${directories.id} IN (SELECT dir_id FROM readable_seed)
        UNION
        SELECT ${directories.id}, ${directories.displayName}, ${directories.parentId}, ${directories.providerDirectoryId}, ${directories.userProfileId}
        FROM ${directories}
        INNER JOIN dir_tree ON dir_tree.${dirParentId} = ${directories.id}
      )
      SELECT DISTINCT
        dir_tree.${dirUserProfileId}      AS ${sql.identifier('ownerUserId')},
        ${userProfiles.email}             AS ${sql.identifier('ownerEmail')},
        ${userProfiles.displayName}       AS ${sql.identifier('ownerDisplayName')},
        dir_tree.${dirId}                 AS ${sql.identifier('dirId')},
        dir_tree.${dirDisplayName}        AS ${sql.identifier('dirDisplayName')},
        dir_tree.${dirParentId}           AS ${sql.identifier('dirParentId')},
        dir_tree.${dirProviderDirectoryId} AS ${sql.identifier('dirProviderDirectoryId')},
        EXISTS (
          SELECT 1 FROM readable_seed WHERE readable_seed.dir_id = dir_tree.${dirId}
        ) AS ${sql.identifier('isReadable')}
      FROM dir_tree
      INNER JOIN ${userProfiles} ON ${userProfiles.id} = dir_tree.${dirUserProfileId}
    `);

    return this.mapDirectoriesInfoToMailboses({
      directorisInfo: result.rows,
      readableProviderDirectoryIds: new Set(
        result.rows.filter((r) => r.isReadable).map((r) => r.dirProviderDirectoryId),
      ),
    });
  }

  private async getMailboxesWithFullAccess(userProfileId: string): Promise<UserMailbox[]> {
    // Full mailbox delegated access: all owner directories
    const fullAccessRows = await this.db
      .select({
        ownerUserId: delegatedAccessAccounts.ownerUserId,
        ownerEmail: userProfiles.email,
        ownerDisplayName: userProfiles.displayName,
        dirId: directories.id,
        dirDisplayName: directories.displayName,
        dirParentId: directories.parentId,
        dirProviderDirectoryId: directories.providerDirectoryId,
      })
      .from(delegatedAccessAccounts)
      .innerJoin(userProfiles, eq(userProfiles.id, delegatedAccessAccounts.ownerUserId))
      .innerJoin(
        directories,
        and(
          eq(directories.userProfileId, delegatedAccessAccounts.ownerUserId),
          eq(directories.ignoreForSync, false),
        ),
      )
      .where(
        and(
          eq(delegatedAccessAccounts.delegateUserId, userProfileId),
          eq(delegatedAccessAccounts.hasFullDelegatedAccess, true),
        ),
      );

    return this.mapDirectoriesInfoToMailboses({
      directorisInfo: fullAccessRows,
      readableProviderDirectoryIds: new Set(
        fullAccessRows.map((item) => item.dirProviderDirectoryId),
      ),
    });
  }

  private mapDirectoriesInfoToMailboses({
    directorisInfo,
    readableProviderDirectoryIds,
  }: {
    readableProviderDirectoryIds: Set<string>;
    directorisInfo: DirectoryInfoRow[];
  }): UserMailbox[] {
    const ownerDirs = new Map<
      string,
      { email: string | null; displayName: string | null; dirs: DirectoryNode[] }
    >();
    for (const row of directorisInfo) {
      let directoriesRef = ownerDirs.get(row.ownerUserId)?.dirs;
      if (isNullish(directoriesRef)) {
        directoriesRef = [];
        ownerDirs.set(row.ownerUserId, {
          email: row.ownerEmail ?? null,
          displayName: row.ownerDisplayName ?? null,
          dirs: directoriesRef,
        });
      }

      directoriesRef.push({
        id: row.dirId,
        displayName: row.dirDisplayName,
        parentId: row.dirParentId,
        providerDirectoryId: row.dirProviderDirectoryId,
      });
    }
    const mailboses: UserMailbox[] = [];
    for (const [, ownerInfo] of ownerDirs) {
      const { directoryTree } = this.buildTree({
        allDirectories: ownerInfo.dirs,
        isReadable: (item) => readableProviderDirectoryIds.has(item.providerDirectoryId),
      });
      mailboses.push({
        email: ownerInfo.email,
        displayName: ownerInfo.displayName,
        isOwn: false,
        folders: directoryTree,
      });
    }
    return mailboses;
  }

  private buildTree({
    allDirectories,
    isReadable,
  }: {
    allDirectories: DirectoryNode[];
    isReadable: (directory: DirectoryNode) => boolean;
  }): {
    directoryTree: UserDirectory[];
    paths: string[];
  } {
    const directoriesByParentId = allDirectories.reduce<Map<string | null, DirectoryNode[]>>(
      (acc, item) => {
        if (acc.has(item.parentId)) {
          acc.get(item.parentId)?.push(item);
        } else {
          acc.set(item.parentId, [item]);
        }
        return acc;
      },
      new Map(),
    );

    const allPaths: string[] = [];
    const buildTreeRecursive = (parentId: string | null, path: string[]): UserDirectory[] => {
      const elements = directoriesByParentId.get(parentId) ?? [];

      return elements.map((element) => {
        const currentPath = [...path, element.displayName];
        allPaths.push(currentPath.join('/'));

        return {
          id: element.providerDirectoryId,
          displayName: element.displayName,
          canReadContent: isReadable(element),
          children: buildTreeRecursive(element.id, [...currentPath]),
        };
      });
    };

    // All root directories have parentId as null.
    const directoryTree = buildTreeRecursive(null, []);
    return {
      directoryTree,
      paths: unique(allPaths),
    };
  }
}

interface DirectoryInfoRowWithReadable extends DirectoryInfoRow, Record<string, unknown> {
  isReadable: boolean;
}

interface DirectoryInfoRow {
  ownerUserId: string;
  ownerEmail: string | null;
  ownerDisplayName: string | null;
  dirId: string;
  dirDisplayName: string;
  dirParentId: string | null;
  dirProviderDirectoryId: string;
}
