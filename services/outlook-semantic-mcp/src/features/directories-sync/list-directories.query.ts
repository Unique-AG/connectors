import { createSmeared, smearPath } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNullish, unique } from 'remeda';
import {
  DRIZZLE,
  type DrizzleDatabase,
  delegatedAccessDirectories,
  delegatedAccessPipelines,
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
  children: UserDirectory[];
}

export interface UserMailbox {
  email: string | null;
  displayName: string | null;
  isOwn: boolean;
  folders: UserDirectory[];
}

@Injectable()
export class ListDirectoriesQuery {
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

    const { directoryTree: ownTree, paths: ownPaths } = this.buildTree(ownDirectories);
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

    const delegatedDirectoryRowsShape = {
      ownerUserId: delegatedAccessPipelines.ownerUserId,
      ownerEmail: userProfiles.email,
      ownerDisplayName: userProfiles.displayName,
      dirId: directories.id,
      dirDisplayName: directories.displayName,
      dirParentId: directories.parentId,
      dirProviderDirectoryId: directories.providerDirectoryId,
    };

    // Directory-level delegated access: specific directories granted via delegatedAccessDirectories
    const directoryLevelRows = await this.db
      .select(delegatedDirectoryRowsShape)
      .from(delegatedAccessPipelines)
      .innerJoin(
        delegatedAccessDirectories,
        eq(delegatedAccessDirectories.pipelineId, delegatedAccessPipelines.id),
      )
      .innerJoin(userProfiles, eq(userProfiles.id, delegatedAccessPipelines.ownerUserId))
      .innerJoin(
        directories,
        and(
          eq(directories.userProfileId, delegatedAccessPipelines.ownerUserId),
          eq(directories.providerDirectoryId, delegatedAccessDirectories.directoryId),
          eq(directories.ignoreForSync, false),
        ),
      )
      .where(
        and(
          eq(delegatedAccessPipelines.delegateUserId, userProfileId),
          eq(delegatedAccessPipelines.hasFullDelegatedAccess, false),
        ),
      );

    // Full mailbox delegated access: all owner directories
    const fullAccessRows = await this.db
      .select(delegatedDirectoryRowsShape)
      .from(delegatedAccessPipelines)
      .innerJoin(userProfiles, eq(userProfiles.id, delegatedAccessPipelines.ownerUserId))
      .innerJoin(
        directories,
        and(
          eq(directories.userProfileId, delegatedAccessPipelines.ownerUserId),
          eq(directories.ignoreForSync, false),
        ),
      )
      .where(
        and(
          eq(delegatedAccessPipelines.delegateUserId, userProfileId),
          eq(delegatedAccessPipelines.hasFullDelegatedAccess, true),
        ),
      );

    const delegatedDirectoryRows = [...directoryLevelRows, ...fullAccessRows];

    if (delegatedDirectoryRows.length === 0) {
      return [ownMailbox];
    }

    const ownerDirs = new Map<
      string,
      { email: string | null; displayName: string | null; dirs: DirectoryNode[] }
    >();
    for (const row of delegatedDirectoryRows) {
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

    const delegatedMailboxes: UserMailbox[] = [];
    for (const [, ownerInfo] of ownerDirs) {
      const { directoryTree } = this.buildTree(ownerInfo.dirs);
      delegatedMailboxes.push({
        email: ownerInfo.email,
        displayName: ownerInfo.displayName,
        isOwn: false,
        folders: directoryTree,
      });
    }

    return [ownMailbox, ...delegatedMailboxes];
  }

  private buildTree(allDirectories: DirectoryNode[]): {
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
