import { Inject, Injectable } from '@nestjs/common';
import { and, eq, isNull, or } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { Directory, DRIZZLE, type DrizzleDatabase, directories } from '~/db';

export interface UserDirectory {
  id: string;
  displayName: string;
  children: UserDirectory[];
}

@Injectable()
export class ListDirectoriesQuery {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Span()
  public async run(userProfileId: string): Promise<UserDirectory[]> {
    const allDirectories = await this.db.query.directories.findMany({
      where: and(
        eq(directories.userProfileId, userProfileId),
        or(isNull(directories.ignoreForSync), eq(directories.ignoreForSync, false)),
      ),
    });

    return this.buildTree(allDirectories);
  }

  private buildTree(allDirectories: Directory[]): UserDirectory[] {
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

    const buildTreeRecursive = (parentId: string | null): UserDirectory[] => {
      const elements = directoriesByParentId.get(parentId) ?? [];
      return elements.map((element) => ({
        id: element.providerDirectoryId,
        displayName: element.displayName,
        children: buildTreeRecursive(element.id),
      }));
    };

    // A directory is a root if it has no parent or its parent was filtered out (ignored for sync)
    return buildTreeRecursive(null);
  }
}
