import { createSmeared, smearPath } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { unique } from 'remeda';
import { Directory, DRIZZLE, type DrizzleDatabase, directories } from '~/db';

export interface UserDirectory {
  id: string;
  displayName: string;
  children: UserDirectory[];
}

@Injectable()
export class ListDirectoriesQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Span()
  public async run(userProfileId: string): Promise<UserDirectory[]> {
    const allDirectories = await this.db.query.directories.findMany({
      where: and(
        eq(directories.userProfileId, userProfileId),
        // We filter out directories ignored for sync because they cannot be used in searches.
        eq(directories.ignoreForSync, false),
      ),
    });

    const { directoryTree, paths } = this.buildTree(allDirectories);
    this.logger.debug({
      msg: `Returned Directories: ${paths.length}`,
      userProfileId,
      directories: paths.map((item) => smearPath(createSmeared(item))).join('\r\n'),
    });

    return directoryTree;
  }

  private buildTree(allDirectories: Directory[]): {
    directoryTree: UserDirectory[];
    paths: string[];
  } {
    const directoriesByParentId = allDirectories.reduce<Map<string | null, Directory[]>>(
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
