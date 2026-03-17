import assert from 'node:assert';
import { MetadataFilter, type UniqueApiClient, UniqueQLOperator } from '@unique-ag/unique-api';
import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNull } from 'remeda';
import * as z from 'zod';
import {
  type Directory,
  DRIZZLE,
  type DrizzleDatabase,
  directories,
  userProfiles,
  SystemDirectoryType,
} from '~/db';
import { MessageMetadata } from '~/features/mail-ingestion/utils/get-metadata-from-message';
import {
  getRootScopeExternalId,
  getRootScopeExternalIdForUser,
} from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { findBestMatch } from '~/utils/find-best-match';
import {
  buildSearchFilter,
  type SearchCondition,
  SearchEmailsInputSchema,
} from './search-conditions.dto';
import { asAllOptions } from '@unique-ag/utils';

export interface SearchEmailResult {
  id: string;
  emailId: string;
  folderId: string;
  title: string;
  from: string;
  receivedDateTime: string | null;
  text: string;
  url: string | undefined;
}

@Injectable()
export class SearchEmailsQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  @Span()
  public async run(
    userProfileId: string,
    input: z.infer<typeof SearchEmailsInputSchema>,
  ): Promise<{ results: SearchEmailResult[]; searchSummary: string | undefined }> {
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User profile not found: ${userProfileId}`);
    assert.ok(userProfile.providerUserId, `providerUserId missing for: ${userProfileId}`);

    const rootScope = await this.uniqueApi.scopes.getByExternalId(getRootScopeExternalId());
    assert.ok(rootScope, `Root scope not found for user: ${userProfile.providerUserId}`);
    const rootScopeForUser = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalIdForUser(userProfile.providerUserId),
    );
    assert.ok(rootScopeForUser, `Root scope not found for user: ${userProfile.providerUserId}`);

    const { conditions: resolvedConditions, searchSummary } = await this.sanitizeSearchConditions(
      userProfileId,
      input.conditions,
    );

    const uniqueQlMetadataFilter = buildSearchFilter(resolvedConditions);
    const metaDataFilter: MetadataFilter = {
      and: [
        {
          operator: UniqueQLOperator.CONTAINS,
          value: `uniquepathid://${rootScope.id}/${rootScopeForUser.id}`,
          path: [`folderIdPath`],
        },
      ],
    };
    if (uniqueQlMetadataFilter) {
      metaDataFilter.and.push(uniqueQlMetadataFilter);
    }
    const searchResult = await this.uniqueApi.content.search({
      prompt: input.search,
      metaDataFilter,
      limit: input.limit,
      scoreThreshold: 0,
    });

    const results = searchResult.map((item) => {
      const metadata = item.metadata as MessageMetadata | undefined;
      return {
        title: item.title ?? '',
        id: item.id,
        text: item.text,
        url: item.url ?? undefined,
        outlookWebLink: metadata?.webLink ?? '',
        emailId: metadata?.id ?? '',
        folderId: metadata?.parentFolderId ?? '',
        from: metadata?.fromEmailAddress ?? '',
        receivedDateTime: metadata?.receivedDateTime ?? '',
      };
    });

    return { results, searchSummary };
  }

  private async sanitizeSearchConditions(
    userProfileId: string,
    conditions: SearchCondition[] | undefined,
  ): Promise<{ conditions: SearchCondition[] | undefined; searchSummary: string | undefined }> {
    const hasDirectoriesCondition = conditions?.some((condition) =>
      isNonNull(condition.directories),
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

      const { resolvedIds, unrecognized } = this.sanitizeWrongDirectoryIds(
        rawDirectoryIds,
        userDirectories,
      );
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

  private sanitizeWrongDirectoryIds(
    rawDirectoryIds: string[],
    userDirectories: Directory[],
  ): { resolvedIds: string[]; unrecognized: string[] } {
    const resolvedIds: string[] = [];
    const unrecognized: string[] = [];

    for (const rawDirectoryId of rawDirectoryIds) {
      if (!rawDirectoryId.trim().length) {
        continue;
      }
      const exactMatch = userDirectories.find(
        ({ providerDirectoryId }) => providerDirectoryId === rawDirectoryId,
      );
      if (exactMatch) {
        resolvedIds.push(rawDirectoryId);
        continue;
      }

      const bestDirectory = findBestMatch({
        items: userDirectories,
        getLabel: (directory) => directory.displayName,
        query: rawDirectoryId,
        threshold: 0.8,
        isNewItemBetter: (newItem, currentBestSimilarity) => {
          if (systemDirectories.includes(currentBestSimilarity?.internalType)) {
            return false;
          }

          return systemDirectories.includes(newItem.internalType);
        },
      });
      if (bestDirectory) {
        resolvedIds.push(bestDirectory.providerDirectoryId);
      } else {
        unrecognized.push(rawDirectoryId);
      }
    }

    return { resolvedIds, unrecognized };
  }
}

const systemDirectories = asAllOptions<SystemDirectoryType>()([
  'Archive',
  'Deleted Items',
  'Drafts',
  'Inbox',
  'Junk Email',
  'Outbox',
  'Sent Items',
  'Conversation History',
  'Recoverable Items Deletions',
  'Clutter',
]) as unknown as string[];
