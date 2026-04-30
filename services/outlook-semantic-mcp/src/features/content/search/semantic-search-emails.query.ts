import assert from 'node:assert';
import { MetadataFilter, type UniqueApiClient, UniqueQLOperator } from '@unique-ag/unique-api';
import { Inject, Injectable } from '@nestjs/common';
import { and, eq, isNotNull, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { filter, isNonNull, isNullish, map, omit, pipe, sortBy } from 'remeda';
import * as z from 'zod';
import {
  DRIZZLE,
  type DrizzleDatabase,
  delegatedAccessDirectories,
  delegatedAccessPipelines,
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

    const { filter: metaDataFilter, searchSummary } = await this.builsSearchConditions({
      userProfile,
      conditions: input.conditions,
    });
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
        const metadata = item.metadata as MessageMetadata | undefined;
        const itemRef = acc[item.id] ?? {
          title: item.title ?? '',
          uniqueContentId: item.id,
          uniqueContentUrl: item.url ?? undefined,
          outlookWebLink: metadata?.webLink ?? '',
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
    searchSummary: string | undefined;
  }> {
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

    const userConditions = await this.scopeSearchToUserProfile({
      scopeIds: [rootScopeId, rootScopeForUserId],
      userProfileId: userProfile.id,
      conditions,
    });

    const searchSummary: string[] = [];
    finalFilters.or.push(userConditions.filter);
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

      const delegatedAccessFilter = await this.scopeSearchToUserProfile({
        scopeIds: [rootScopeId, ownerRootScopeId],
        userProfileId: ownerUserId,
        conditions,
        delegatedAccessFilters: { msGraphDirectoryIds },
      });

      finalFilters.or.push(delegatedAccessFilter.filter);
      if (delegatedAccessFilter.searchSummary) {
        searchSummary.push(
          `Delegated access to mailbox ${ownerUserEmail}: ${delegatedAccessFilter.searchSummary}`,
        );
      }
    }

    return {
      filter: finalFilters,
      searchSummary: searchSummary.length > 0 ? searchSummary.join(`\r\n`) : undefined,
    };
  }

  private async scopeSearchToUserProfile({
    scopeIds,
    userProfileId,
    conditions,
    delegatedAccessFilters,
  }: {
    userProfileId: string;
    scopeIds: string[];
    conditions: z.infer<typeof SearchEmailsInputSchema>['conditions'];
    delegatedAccessFilters?: {
      msGraphDirectoryIds: string[];
    };
  }): Promise<{ filter: MetadataFilter; searchSummary: string | undefined }> {
    const { conditions: resolvedConditions, searchSummary } =
      await this.sanitizeSearchConditionsForUserQuery.run(userProfileId, conditions);

    const uniqueQlMetadataFilter = buildSearchFilter(resolvedConditions);
    const scopedMetadataFilter: MetadataFilter = {
      and: [
        {
          operator: UniqueQLOperator.CONTAINS,
          value: `uniquepathid://${scopeIds.join('/')}`,
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
}
