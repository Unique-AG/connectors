import { CACHE_MANAGER } from '@nestjs/cache-manager';
import { Inject, Injectable } from '@nestjs/common';
import { Cache } from 'cache-manager';
import { eq } from 'drizzle-orm';
import { DRIZZLE, type DrizzleDatabase, directories } from '~/db';

const FOLDER_PATHS_TTL_MS = 600_000;

export function folderPathsCacheKey(userProfileId: string): string {
  return `folder-paths:${userProfileId}`;
}

@Injectable()
export class GetFolderPathsQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(CACHE_MANAGER) private readonly cacheManager: Cache,
  ) {}

  public async run(userProfileId: string): Promise<Record<string, string>> {
    const cacheKey = folderPathsCacheKey(userProfileId);

    const cached = await this.cacheManager.get<Record<string, string>>(cacheKey);
    if (cached !== undefined && cached !== null) {
      return cached;
    }

    const allDirectories = await this.db.query.directories.findMany({
      where: eq(directories.userProfileId, userProfileId),
    });

    const result = buildFolderPaths(allDirectories);

    await this.cacheManager.set(cacheKey, result, FOLDER_PATHS_TTL_MS);

    return result;
  }
}

function buildFolderPaths(
  allDirectories: {
    id: string;
    providerDirectoryId: string;
    displayName: string;
    parentId: string | null;
  }[],
): Record<string, string> {
  const byId = new Map(allDirectories.map((d) => [d.id, d]));

  const getPath = (id: string): string => {
    const dir = byId.get(id);
    if (!dir) {
      return '';
    }
    if (dir.parentId === null) {
      return `/${dir.displayName}`;
    }
    const parentPath = getPath(dir.parentId);
    return `${parentPath}/${dir.displayName}`;
  };

  const result: Record<string, string> = {};
  for (const dir of allDirectories) {
    result[dir.providerDirectoryId] = getPath(dir.id);
  }
  return result;
}
