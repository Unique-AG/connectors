import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { clone, isNonNullish } from 'remeda';
import { DRIZZLE, DrizzleDatabase, directories } from '~/db';
import { SearchCondition } from './search-conditions.dto';
import { resolveDirectoryIds } from './resolve-directory-ids.util';

@Injectable()
export class CleanupSearchConditionsForUserQuery {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  // We check the search conditions and try fix directories to replace directory names to directory ids for
  // Unique ql query.
  public async run(
    userProfileId: string,
    conditions: SearchCondition[] | undefined,
  ): Promise<{ conditions: SearchCondition[] | undefined; searchSummary: string | undefined }> {
    // We mutate conditions in the sanitization process and to ensure we do not mutate the input we clone them.
    conditions = clone(conditions);
    const hasDirectoriesCondition = conditions?.some((condition) =>
      isNonNullish(condition.directories),
    );
    if (!hasDirectoriesCondition) {
      return { conditions, searchSummary: undefined };
    }

    const userDirectories = await this.db
      .select()
      .from(directories)
      .where(
        and(eq(directories.userProfileId, userProfileId), eq(directories.ignoreForSync, false)),
      );

    const allUnrecognized: string[] = [];
    const resolvedConditions: SearchCondition[] = [];

    for (const condition of conditions ?? []) {
      if (!condition.directories) {
        resolvedConditions.push(condition);
        continue;
      }
      const rawDirectoryIds = Array.isArray(condition.directories.value)
        ? condition.directories.value
        : [condition.directories.value];

      const { resolvedIds, unrecognized } = resolveDirectoryIds(rawDirectoryIds, userDirectories);
      allUnrecognized.push(...unrecognized);

      if (resolvedIds.length === 0) {
        delete condition.directories;
        if (Object.keys(condition).length > 0) {
          resolvedConditions.push(condition);
        }
        continue;
      }

      resolvedConditions.push({
        ...condition,
        directories: {
          ...condition.directories,
          value: resolvedIds,
        },
      });
    }

    let searchSummary: string | undefined;
    if (allUnrecognized.length > 0) {
      const quoted = allUnrecognized.map((f) => `\`"${f}"\``).join(', ');
      searchSummary = `> **Note:** The following folder(s) were not recognized and were excluded from the search: ${quoted}. The search ran across all available folders instead.`;
    }

    return { conditions: resolvedConditions, searchSummary };
  }
}
