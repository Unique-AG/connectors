import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { sql } from 'drizzle-orm';
import { Directory, DirectoryType, DRIZZLE, DrizzleDatabase, directories } from '~/db';

@Injectable()
export class UpsertDirectoryCommand {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

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

    const updateQuery = !updateOnConflict
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

    const newDirectories = await updateQuery.returning();
    const newDirectory = newDirectories.at(0);
    assert.ok(newDirectory, `Counld not create new directory`);
    return newDirectory;
  }
}
