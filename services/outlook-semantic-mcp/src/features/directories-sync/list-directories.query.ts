import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
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
        // We filter out directories ignored for sync because they cannot be used in searches.
        eq(directories.ignoreForSync, false),
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

    // All root directories have parentId as null.
    return buildTreeRecursive(null);
  }
}
