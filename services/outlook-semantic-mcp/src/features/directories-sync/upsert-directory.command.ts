import assert from 'node:assert';
import { CACHE_MANAGER } from '@nestjs/cache-manager';
import { Inject, Injectable } from '@nestjs/common';
import { Cache } from 'cache-manager';
import { and, eq, sql } from 'drizzle-orm';
import { Directory, DirectoryType, DRIZZLE, DrizzleDatabase, directories } from '~/db';
import { folderPathsCacheKey } from './get-folder-paths.query';

@Injectable()
export class UpsertDirectoryCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(CACHE_MANAGER) private readonly cacheManager: Cache,
  ) {}

  public async run({
    parentId,
    userProfileId,
    directory,
    updateOnConflict,
  }: {
    parentId: string | null;
    userProfileId: string;
    directory: { id: string; displayName: string; type: DirectoryType };
    updateOnConflict: boolean;
  }): Promise<Directory> {
    const initialUpdateQuery = this.db.insert(directories).values({
      userProfileId,
      parentId,
      displayName: directory.displayName,
      internalType: directory.type,
      providerDirectoryId: directory.id,
    });

    const upsertQuery = !updateOnConflict
      ? initialUpdateQuery.onConflictDoNothing({
          target: [directories.userProfileId, directories.providerDirectoryId],
        })
      : initialUpdateQuery.onConflictDoUpdate({
          target: [directories.userProfileId, directories.providerDirectoryId],
          set: {
            parentId: sql.raw(`excluded.${directories.parentId.name}`),
            displayName: sql.raw(`excluded.${directories.displayName.name}`),
          },
        });

    // We use .execute() instead of returning() because typescript types are wrong if we use
    // onConflictDoNothing => It always returns an array with no results. So we have to save and then read again.
    await upsertQuery.execute();
    const newDirectory = await this.db.query.directories.findFirst({
      where: and(
        eq(directories.userProfileId, userProfileId),
        eq(directories.providerDirectoryId, directory.id),
      ),
    });
    assert.ok(newDirectory, `Could not create new directory`);
    await this.cacheManager.del(folderPathsCacheKey(userProfileId));
    return newDirectory;
  }
}
