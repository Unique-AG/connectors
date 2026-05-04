import assert from 'node:assert';
import { MetadataFilter, type UniqueApiClient, UniqueQLOperator } from '@unique-ag/unique-api';
import { Inject, Injectable } from '@nestjs/common';
import { and, eq, isNotNull, notInArray, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { filter, isNonNull, isNullish, map, omit, pipe, sortBy } from 'remeda';
import * as z from 'zod';
import {
  DRIZZLE,
  type DrizzleDatabase,
  delegatedAccessDirectories,
  delegatedAccessPipelines,
  directories,
  UserProfile,
  userProfiles,
} from '~/db';
import { MessageMetadata } from '~/features/process-email/utils/get-metadata-from-message';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import {
  getRootScopeExternalId,
  getRootScopeExternalIdForUser,
} from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { concatChunks } from '~/utils/concat-chunks';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { Nullish } from '~/utils/nullish';
import { buildSearchFilter } from './build-unique-ql-search-filter.util';
import { filterConditionsForMailbox as filterConditionsForMailbox } from './filter-conditions-for-mailbox';
import { SanitizeSearchConditionsForUserQuery } from './sanitize-search-conditions-for-user.query';
import { SearchEmailsInputSchema } from './semantic-search-conditions.dto';

export enum SearchBackend {
  Unique = 'Unique',
  MsGraph = 'MsGraph',
}

export interface SearchEmailResult {
  uniqueContentId?: string;
  msGraphMessageId?: string;
  folderId: string;
  title: string;
  from: string;
  sourceMailbox: Nullish<string>;
  outlookWebLink: string;
  receivedDateTime: string | null;
  text: string;
  uniqueContentUrl: string | undefined;
  backend: SearchBackend;
}

@Injectable()
export class SemanticSearchEmailsQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly sanitizeSearchConditionsForUserQuery: SanitizeSearchConditionsForUserQuery,
  ) {}

  @Span()
  public async run(
    userProfileTypeId: UserProfileTypeID,
    input: z.infer<typeof SearchEmailsInputSchema>,
  ): Promise<{ results: SearchEmailResult[]; searchSummary: string | undefined }> {
    const userProfile = await this.getUserProfileQuery.run(userProfileTypeId);

    const {
      filter: metaDataFilter,
      hasActiveBranches,
      searchSummary,
      mapUniqueFolderPathToOwnerEmail,
    } = await this.builsSearchConditions({
      userProfile,
      conditions: input.conditions,
    });

    if (!hasActiveBranches) {
      return {
        results: [],
        searchSummary: 'No accessible mailbox matched the requested mailbox filter(s)',
      };
    }

    const searchResults = await this.uniqueApi.content.search({
      prompt: input.search,
      metaDataFilter,
      limit: input.limit,
      scoreThreshold: 0,
    });

    type DeduplicatedResult = Omit<SearchEmailResult, 'text'> & {
      textParts: { order: number; text: string }[];
      index: number;
    };

    const resultsDeduplicated = searchResults.reduce<Record<string, DeduplicatedResult>>(
      (acc, item, index) => {
        const metadata = item.metadata as (MessageMetadata & { folderIdPath?: string }) | undefined;
        const sourceMailbox =
          mapUniqueFolderPathToOwnerEmail.find(({ uniqueFolderIdPath }) => {
            return metadata?.folderIdPath?.startsWith(uniqueFolderIdPath);
          })?.ownerEmail ?? null;

        const itemRef = acc[item.id] ?? {
          title: item.title ?? '',
          uniqueContentId: item.id,
          uniqueContentUrl: item.url ?? undefined,
          outlookWebLink: metadata?.webLink ?? '',
          sourceMailbox,
          msGraphMessageId: metadata?.id || undefined,
          folderId: metadata?.parentFolderId ?? '',
          from: metadata?.fromEmailAddress ?? '',
          receivedDateTime: metadata?.receivedDateTime ?? '',
          backend: SearchBackend.Unique,
          textParts: [],
          index,
        };
        itemRef.textParts.push({ order: item.order, text: item.text });
        acc[item.id] = itemRef;
        return acc;
      },
      {},
    );

    const results: SearchEmailResult[] = pipe(
      Object.values(resultsDeduplicated),
      sortBy((item) => item.index),
      map(({ textParts, ...searchResult }) => {
        return {
          ...omit(searchResult, ['index']),
          text: concatChunks(textParts),
        };
      }),
    );

    return { results, searchSummary };
  }

  private async builsSearchConditions({
    userProfile,
    conditions,
  }: {
    conditions: z.infer<typeof SearchEmailsInputSchema>['conditions'];
    userProfile: NonNullishProps<UserProfile, 'email'>;
  }): Promise<{
    filter: MetadataFilter;
    hasActiveBranches: boolean;
    searchSummary: string | undefined;
    mapUniqueFolderPathToOwnerEmail: { uniqueFolderIdPath: string; ownerEmail: string }[];
  }> {
    const directoriesIgnoredForSync = this.db
      .selectDistinct({ microsoftDirectoryId: directories.providerDirectoryId })
      .from(directories)
      .where(eq(directories.ignoreForSync, true));

    const delegatedAcceses = await this.db
      .select({
        ownerUserEmail: sql<string>`${userProfiles.email}`,
        ownerUserId: delegatedAccessPipelines.ownerUserId,
        ownerProviderUserId: sql<string>`${userProfiles.providerUserId}`,
        msGraphDirectoryIds: sql<string[]>`array_agg(${delegatedAccessDirectories.directoryId})`,
      })
      .from(delegatedAccessPipelines)
      .innerJoin(
        delegatedAccessDirectories,
        eq(delegatedAccessPipelines.id, delegatedAccessDirectories.pipelineId),
      )
      .innerJoin(userProfiles, eq(delegatedAccessPipelines.ownerUserId, userProfiles.id))
      .where(
        and(
          isNotNull(userProfiles.providerUserId),
          isNotNull(userProfiles.email),
          eq(delegatedAccessPipelines.delegateUserId, userProfile.id),
          notInArray(delegatedAccessDirectories.directoryId, directoriesIgnoredForSync),
        ),
      )
      .groupBy(
        userProfiles.providerUserId,
        userProfiles.email,
        delegatedAccessPipelines.ownerUserId,
      );

    const scopes = await this.uniqueApi.scopes.getByExternalIds([
      getRootScopeExternalId(),
      getRootScopeExternalIdForUser(userProfile.providerUserId),
      ...delegatedAcceses.map((item) => getRootScopeExternalIdForUser(item.ownerProviderUserId)),
    ]);

    const scopeIds = pipe(
      scopes,
      map((scope): [Nullish<string>, string] => [scope.externalId, scope.id]),
      filter((items) => items.every(isNonNull)),
    ) as [string, string][];
    const scopeExternalIdToScopeId = new Map<string, string>(scopeIds);

    const rootScopeId = scopeExternalIdToScopeId.get(getRootScopeExternalId());
    assert.ok(rootScopeId, `Mcp root scope not found: ${userProfile.providerUserId}`);
    const rootScopeForUserId = scopeExternalIdToScopeId.get(
      getRootScopeExternalIdForUser(userProfile.providerUserId),
    );
    assert.ok(rootScopeForUserId, `Root scope not found for user: ${userProfile.providerUserId}`);

    const finalFilters: MetadataFilter = { or: [] };
    let hasActiveBranches = false;
    const mapUniqueFolderPathToOwnerEmail: Map<string, string> = new Map();

    const currentUserScopeIdsFromRoot = [rootScopeId, rootScopeForUserId];
    const userConditions = await this.scopeSearchToUserProfile({
      scopeIdsFromRoot: currentUserScopeIdsFromRoot,
      userProfileId: userProfile.id,
      userEmail: userProfile.email,
      conditions,
    });

    const searchSummary: string[] = [];
    if (userConditions.filter !== null) {
      hasActiveBranches = true;
      mapUniqueFolderPathToOwnerEmail.set(
        this.getUniqueFolderPath(currentUserScopeIdsFromRoot),
        userProfile.email,
      );
      finalFilters.or.push(userConditions.filter);
    }
    if (userConditions.searchSummary) {
      searchSummary.push(`${userProfile.email}: ${userConditions.searchSummary}`);
    }

    for (const {
      ownerUserEmail,
      ownerUserId,
      ownerProviderUserId,
      msGraphDirectoryIds,
    } of delegatedAcceses) {
      const ownerRootScopeId = scopeExternalIdToScopeId.get(
        getRootScopeExternalIdForUser(ownerProviderUserId),
      );
      // To ensure we build a valid set of filters and that the current user
      // has delegated access we double check in memory every variable which would
      // affect the delegated access filtering to avoid filtering on an inbox which
      // you should not have access.
      if (
        !msGraphDirectoryIds.length ||
        isNullish(ownerProviderUserId) ||
        isNullish(ownerUserEmail) ||
        isNullish(ownerUserId) ||
        isNullish(ownerRootScopeId)
      ) {
        continue;
      }

      const ownerScopeIdsFromRoot = [rootScopeId, ownerRootScopeId];
      const delegatedAccessFilter = await this.scopeSearchToUserProfile({
        scopeIdsFromRoot: ownerScopeIdsFromRoot,
        userProfileId: ownerUserId,
        userEmail: ownerUserEmail,
        conditions,
        delegatedAccessFilters: { msGraphDirectoryIds },
      });

      if (delegatedAccessFilter.filter !== null) {
        hasActiveBranches = true;
        mapUniqueFolderPathToOwnerEmail.set(
          this.getUniqueFolderPath(ownerScopeIdsFromRoot),
          ownerUserEmail,
        );
        finalFilters.or.push(delegatedAccessFilter.filter);
      }
      if (delegatedAccessFilter.searchSummary) {
        searchSummary.push(
          `Delegated access to mailbox ${ownerUserEmail}: ${delegatedAccessFilter.searchSummary}`,
        );
      }
    }

    return {
      filter: finalFilters,
      hasActiveBranches,
      mapUniqueFolderPathToOwnerEmail: Array.from(mapUniqueFolderPathToOwnerEmail).map((item) => ({
        uniqueFolderIdPath: item[0],
        ownerEmail: item[1],
      })),
      searchSummary: searchSummary.length > 0 ? searchSummary.join(`\r\n`) : undefined,
    };
  }

  private async scopeSearchToUserProfile({
    scopeIdsFromRoot,
    userProfileId,
    userEmail,
    conditions,
    delegatedAccessFilters,
  }: {
    userProfileId: string;
    scopeIdsFromRoot: string[];
    userEmail: string;
    conditions: z.infer<typeof SearchEmailsInputSchema>['conditions'];
    delegatedAccessFilters?: {
      msGraphDirectoryIds: string[];
    };
  }): Promise<{ filter: MetadataFilter | null; searchSummary: string | undefined }> {
    const conditionsForCurrentMailbox = filterConditionsForMailbox(conditions, userEmail);

    if (conditions?.length && !conditionsForCurrentMailbox.length) {
      return { filter: null, searchSummary: undefined };
    }

    const { conditions: resolvedConditions, searchSummary } =
      await this.sanitizeSearchConditionsForUserQuery.run(
        userProfileId,
        conditionsForCurrentMailbox,
      );

    const uniqueQlMetadataFilter = buildSearchFilter(resolvedConditions);
    const scopedMetadataFilter: MetadataFilter = {
      and: [
        {
          operator: UniqueQLOperator.CONTAINS,
          value: this.getUniqueFolderPath(scopeIdsFromRoot),
          path: [`folderIdPath`],
        },
      ],
    };

    const msGraphDirectoryIds = delegatedAccessFilters?.msGraphDirectoryIds;
    if (Array.isArray(msGraphDirectoryIds) && msGraphDirectoryIds.length > 0) {
      const msGraphDirectoryId: keyof Pick<MessageMetadata, 'parentFolderId'> = 'parentFolderId';

      scopedMetadataFilter.and.push({
        operator: UniqueQLOperator.IN,
        value: msGraphDirectoryIds,
        path: [msGraphDirectoryId],
      });
    }

    if (uniqueQlMetadataFilter) {
      scopedMetadataFilter.and.push(uniqueQlMetadataFilter);
    }

    return { filter: scopedMetadataFilter, searchSummary };
  }

  private getUniqueFolderPath(scopeIdsFromRoot: string[]): string {
    return `uniquepathid://${scopeIdsFromRoot.join('/')}`;
  }
}
