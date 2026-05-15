import assert from 'node:assert';
import {
  MetadataFilter,
  SearchResultItem,
  type UniqueApiClient,
  UniqueQLOperator,
} from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, isNonNullish, isNullish, map, pick, pipe, sortBy } from 'remeda';
import * as z from 'zod';
import { UserProfile } from '~/db';
import { GetDelegatedAccessQuery } from '~/features/delegated-access/queries/get-delegates-access.query';
import { MessageMetadata } from '~/features/process-email/utils/get-metadata-from-message';
import { traceError } from '~/features/tracing.utils';
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
import { buildUniqueQlSearchFilter } from './build-unique-ql-search-filter.util';
import { CleanupSearchConditionsForUserQuery } from './cleanup-search-conditions-for-user.query';
import { SemanticSearchConfig } from './search.config';
import { SearchEmailsInputSchema } from './search-conditions.dto';

export enum SearchBackend {
  Unique = 'Unique',
  MsGraph = 'MsGraph',
}

export interface OpenEmailParams {
  id: string;
  idType: SearchBackend;
  mailbox?: string;
  parentFolderId?: string;
  idIsImmutable?: boolean;
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
  openEmailParams: OpenEmailParams;
}

interface DelegatedAccess {
  ownerUserEmail: string;
  ownerUserId: string;
  ownerProviderUserId: string;
  msGraphDirectoryIds: string[];
}

interface AccessContext {
  rootScopeId: string;
  rootScopeForUserId: string;
  delegatedAccesses: DelegatedAccess[];
  scopeExternalIdToScopeId: Map<string, string>;
  mapUniqueFolderPathToOwnerEmail: {
    uniqueFolderIdPath: string;
    ownerEmail: string;
  }[];
}

interface ValidSearchJobInput {
  search: string;
  limit: number | undefined;
  filter: MetadataFilter;
  isScoped: true;
  searchSummary: string | undefined;
}

type SearchJobInput = { isScoped: false } | ValidSearchJobInput;

@Injectable()
export class SemanticSearchEmailsQuery {
  public constructor(
    private readonly getDelegatedAccessQuery: GetDelegatedAccessQuery,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly cleanupSearchConditionsForUserQuery: CleanupSearchConditionsForUserQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    inputs: z.infer<typeof SearchEmailsInputSchema>[],
    searchConfig: SemanticSearchConfig,
  ): Promise<{
    results: SearchEmailResult[];
    searchSummary: string | undefined;
  }> {
    assert.ok(searchConfig, `searchConfig cannot be nullish`);
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const context = await this.loadAccessContext(userProfile);

    const searchJobsInputs = await Promise.all(
      inputs.map((input) => this.buildUniqueQlSearchInput(input, userProfile, context)),
    );
    const searchJobs = searchJobsInputs.filter((job): job is ValidSearchJobInput => job.isScoped);

    const uniqueQlSearchResults = await Promise.allSettled(
      searchJobs.map((job) =>
        this.uniqueApi.content.search({
          prompt: job.search,
          metaDataFilter: job.filter,
          limit: job.limit,
          scoreThreshold: 0,
        }),
      ),
    );

    const accumulated = new Map<
      string,
      {
        index: number;
        content: Pick<SearchResultItem, 'metadata' | 'id' | 'title' | 'url'>;
        chunks: Map<string, SearchResultItem>;
      }
    >();
    const summaries: string[] = [];

    for (const [i, settledItem] of uniqueQlSearchResults.entries()) {
      const job = searchJobs[i];
      if (isNullish(job)) {
        continue;
      }

      if (job.searchSummary) {
        summaries.push(job.searchSummary);
      }

      if (settledItem.status === 'rejected') {
        traceError(settledItem.reason);
        continue;
      }
      settledItem.value.forEach((item, index) => {
        const itemRef = accumulated.get(item.id);
        if (itemRef) {
          itemRef.index = Math.min(itemRef.index, index);
          if (!itemRef.chunks.has(item.chunkId)) {
            itemRef.chunks.set(item.chunkId, item);
          }
          return;
        }
        accumulated.set(item.id, {
          index,
          content: pick(item, ['id', 'title', 'url', 'metadata']),
          chunks: new Map([[item.chunkId, item]]),
        });
      });
    }

    const results = pipe(
      Array.from(accumulated.values()),
      sortBy((item) => item.index),
      map((item): SearchEmailResult => {
        const metadata = item.content?.metadata as
          | (MessageMetadata & { folderIdPath?: string })
          | undefined;

        const sourceMailbox =
          context.mapUniqueFolderPathToOwnerEmail.find(({ uniqueFolderIdPath }) => {
            return metadata?.folderIdPath?.startsWith(uniqueFolderIdPath);
          })?.ownerEmail ?? null;

        return {
          title: item.content.title ?? '',
          uniqueContentId: item.content.id,
          uniqueContentUrl: item.content.url ?? undefined,
          // OWA deep links require full mailbox access. Folder-level delegates receive an
          // AccessDeniedException when following them. Since we cannot distinguish full from
          // folder-level access at query time, we suppress the link for all delegated mailboxes.
          outlookWebLink: userProfile.email === sourceMailbox ? (metadata?.webLink ?? '') : '',
          sourceMailbox,
          msGraphMessageId: metadata?.id || undefined,
          folderId: metadata?.parentFolderId ?? '',
          from: metadata?.fromEmailAddress ?? '',
          receivedDateTime: metadata?.receivedDateTime ?? '',
          backend: SearchBackend.Unique,
          text: concatChunks(Array.from(item.chunks.values())),
          openEmailParams: {
            id: item.content.id,
            idType: SearchBackend.Unique,
          },
        };
      }),
    );

    return {
      results: results.slice(0, searchConfig.maxEmailsLimit),
      searchSummary: summaries.length > 0 ? summaries.join('\r\n') : undefined,
    };
  }

  private async loadAccessContext(
    userProfile: NonNullishProps<UserProfile, 'email'>,
  ): Promise<AccessContext> {
    const delegatedAccesses = await this.getDelegatedAccessQuery.run(userProfile.id);
    const scopes = await this.uniqueApi.scopes.getByExternalIds([
      getRootScopeExternalId(),
      getRootScopeExternalIdForUser(userProfile.providerUserId),
      ...delegatedAccesses.map((item) => getRootScopeExternalIdForUser(item.ownerProviderUserId)),
    ]);

    const scopeIds = pipe(
      scopes,
      map((scope): [Nullish<string>, string] => [scope.externalId, scope.id]),
      filter((items) => items.every(isNonNullish)),
    ) as [string, string][];
    const scopeExternalIdToScopeId = new Map<string, string>(scopeIds);

    const rootScopeId = scopeExternalIdToScopeId.get(getRootScopeExternalId());
    assert.ok(rootScopeId, `Mcp root scope not found: ${userProfile.providerUserId}`);
    const rootScopeForUserId = scopeExternalIdToScopeId.get(
      getRootScopeExternalIdForUser(userProfile.providerUserId),
    );
    assert.ok(rootScopeForUserId, `Root scope not found for user: ${userProfile.providerUserId}`);

    const mapUniqueFolderPathToOwnerEmail: {
      uniqueFolderIdPath: string;
      ownerEmail: string;
    }[] = [
      {
        uniqueFolderIdPath: this.getUniqueFolderPath([rootScopeId, rootScopeForUserId]),
        ownerEmail: userProfile.email,
      },
    ];

    for (const {
      ownerUserEmail,
      ownerUserId,
      ownerProviderUserId,
      msGraphDirectoryIds,
    } of delegatedAccesses) {
      const ownerRootScopeId = scopeExternalIdToScopeId.get(
        getRootScopeExternalIdForUser(ownerProviderUserId),
      );
      if (
        !msGraphDirectoryIds.length ||
        isNullish(ownerProviderUserId) ||
        isNullish(ownerUserEmail) ||
        isNullish(ownerUserId) ||
        isNullish(ownerRootScopeId)
      ) {
        continue;
      }
      mapUniqueFolderPathToOwnerEmail.push({
        uniqueFolderIdPath: this.getUniqueFolderPath([rootScopeId, ownerRootScopeId]),
        ownerEmail: ownerUserEmail,
      });
    }

    return {
      rootScopeId,
      rootScopeForUserId,
      delegatedAccesses,
      scopeExternalIdToScopeId,
      mapUniqueFolderPathToOwnerEmail,
    };
  }

  private async buildUniqueQlSearchInput(
    input: z.infer<typeof SearchEmailsInputSchema>,
    userProfile: NonNullishProps<UserProfile, 'email'>,
    context: AccessContext,
  ): Promise<SearchJobInput> {
    const { rootScopeId, rootScopeForUserId, delegatedAccesses, scopeExternalIdToScopeId } =
      context;

    const finalFilters: MetadataFilter = { or: [] };
    const searchSummaryParts: string[] = [];

    if (!input.mailbox || input.mailbox === userProfile.email) {
      const userConditions = await this.scopeSearchToUserProfile({
        scopeIdsFromRoot: [rootScopeId, rootScopeForUserId],
        userProfileId: userProfile.id,
        conditions: input.conditions,
      });

      finalFilters.or.push(userConditions.filter);
      if (userConditions.searchSummary) {
        searchSummaryParts.push(`${userProfile.email}: ${userConditions.searchSummary}`);
      }
    }

    let delegatedAccessToSearch = input.mailbox
      ? delegatedAccesses.filter((item) => item.ownerUserEmail === input.mailbox)
      : delegatedAccesses;
    // Double checked here -> the query enforces them but we double check them here
    delegatedAccessToSearch = delegatedAccessToSearch.filter((item) => {
      return (
        item.msGraphDirectoryIds.length > 0 &&
        [item.ownerProviderUserId, item.ownerUserEmail, item.ownerUserId].every(isNonNullish)
      );
    });

    for (const {
      ownerUserEmail,
      ownerUserId,
      ownerProviderUserId,
      msGraphDirectoryIds,
    } of delegatedAccessToSearch) {
      const ownerRootScopeId = scopeExternalIdToScopeId.get(
        getRootScopeExternalIdForUser(ownerProviderUserId),
      );
      if (isNullish(ownerRootScopeId)) {
        continue;
      }

      const delegatedFilter = await this.scopeSearchToUserProfile({
        scopeIdsFromRoot: [rootScopeId, ownerRootScopeId],
        userProfileId: ownerUserId,
        conditions: input.conditions,
        delegatedAccessFilters: { msGraphDirectoryIds },
      });

      if (isNonNullish(delegatedFilter.filter)) {
        finalFilters.or.push(delegatedFilter.filter);

        if (delegatedFilter.searchSummary) {
          searchSummaryParts.push(
            `Delegated access to mailbox ${ownerUserEmail}: ${delegatedFilter.searchSummary}`,
          );
        }
      }
    }

    if (!finalFilters.or.length) {
      return { isScoped: false };
    }

    return {
      search: input.search,
      limit: input.limit,
      filter: finalFilters,
      isScoped: true,
      searchSummary: searchSummaryParts.length > 0 ? searchSummaryParts.join('\r\n') : undefined,
    };
  }

  private async scopeSearchToUserProfile({
    scopeIdsFromRoot,
    userProfileId,
    conditions,
    delegatedAccessFilters,
  }: {
    userProfileId: string;
    scopeIdsFromRoot: string[];
    conditions: z.infer<typeof SearchEmailsInputSchema>['conditions'];
    delegatedAccessFilters?: {
      msGraphDirectoryIds: string[];
    };
  }): Promise<{ filter: MetadataFilter; searchSummary: string | undefined }> {
    const { conditions: resolvedConditions, searchSummary } =
      await this.cleanupSearchConditionsForUserQuery.run(userProfileId, conditions);

    const uniqueQlMetadataFilter = buildUniqueQlSearchFilter(resolvedConditions);
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
