import assert from 'node:assert';
import {
  MetadataFilter,
  SearchResultItem,
  type UniqueApiClient,
  UniqueQLOperator,
} from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { filter, isNonNullish, isNullish, map, pick, pipe, sortBy, unique } from 'remeda';
import { UserProfile } from '~/db';
import { GetDelegatedAccessQuery } from '~/features/delegated-access/queries/get-delegates-access.query';
import {
  BuildWebLinksCommand,
  webLinkMapKey,
} from '~/features/graph-utils/build-web-links.command';
import { MessageMetadata } from '~/features/process-email/utils/get-metadata-from-message';
import { traceError } from '~/features/tracing.utils';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import {
  getRootScopeExternalId,
  getRootScopeExternalIdForUser,
} from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { concatChunks } from '~/utils/concat-chunks';
import { convertDateTimeToTimezone } from '~/utils/convert-datetime-to-timezone';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { Nullish } from '~/utils/nullish';
import { buildUniqueQlSearchFilter } from './build-unique-ql-search-filter.util';
import { CleanupSearchConditionsForUserQuery } from './cleanup-search-conditions-for-user.query';
import {
  BackendPage,
  StoredSearchCursor,
  UniqueSearchCursorPayload,
} from './cursors/search-cursor.payload';
import { SEARCH_CONFIG } from './search.config';
import { SearchEmailsInput } from './search-conditions.dto';
import { SearchBackend, SearchEmailResult, SearchPageStatus } from './search-results.types';

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
  filter: MetadataFilter;
  isScoped: true;
  searchSummary: string | undefined;
}

type SearchJobInput = { isScoped: false } | ValidSearchJobInput;

// One semantic search page: the first page of a search, or the page a cursor points at.
interface SemanticPageJob {
  input: SearchEmailsInput;
  // Unique search pages start at 1; page 0 returns the same results as page 1.
  page: number;
  seenChunkIds: string[];
  sourceCursorId?: string;
}

export interface SemanticSearchOutput {
  results: SearchEmailResult[];
  pages: BackendPage[];
  searchSummary: string | undefined;
}

interface AccumulatedContent {
  index: number;
  content: Pick<SearchResultItem, 'metadata' | 'id' | 'title' | 'url'>;
  chunks: Map<string, SearchResultItem>;
}

@Injectable()
export class SemanticSearchEmailsQuery {
  public constructor(
    private readonly getDelegatedAccessQuery: GetDelegatedAccessQuery,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly cleanupSearchConditionsForUserQuery: CleanupSearchConditionsForUserQuery,
    private readonly buildWebLinksCommand: BuildWebLinksCommand,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    inputs: SearchEmailsInput[],
    outputTimeZone?: string,
  ): Promise<SemanticSearchOutput> {
    return this.executePages(
      userProfileId,
      inputs.map((input) => ({ input, page: 1, seenChunkIds: [] })),
      outputTimeZone,
    );
  }

  @Span()
  public async fetchNextPages(
    userProfileId: UserProfileTypeID,
    cursors: StoredSearchCursor<UniqueSearchCursorPayload>[],
    outputTimeZone?: string,
  ): Promise<SemanticSearchOutput> {
    return this.executePages(
      userProfileId,
      cursors.map(({ id, payload }) => ({
        input: payload.input,
        page: payload.page,
        seenChunkIds: payload.seenChunkIds,
        sourceCursorId: id,
      })),
      outputTimeZone,
    );
  }

  private async executePages(
    userProfileId: UserProfileTypeID,
    jobs: SemanticPageJob[],
    outputTimeZone: string | undefined,
  ): Promise<SemanticSearchOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const context = await this.loadAccessContext(userProfile);

    // The filter is rebuilt on every page so access revoked since the first page is honoured.
    const searchJobInputs = await Promise.all(
      jobs.map((job) => this.buildUniqueQlSearchInput(job.input, userProfile, context)),
    );

    const settledSearches = await Promise.allSettled(
      jobs.map((job, i) => {
        const searchJobInput = searchJobInputs[i];
        if (!searchJobInput?.isScoped) {
          return Promise.resolve(null);
        }
        return this.uniqueApi.content.search({
          prompt: searchJobInput.search,
          metaDataFilter: searchJobInput.filter,
          limit: this.getPageSize(job),
          page: job.page,
          scoreThreshold: 0,
        });
      }),
    );

    const chunkLists: SearchResultItem[][] = [];
    const pages: BackendPage[] = [];
    const summaries: string[] = [];

    for (const [i, job] of jobs.entries()) {
      const searchJobInput = searchJobInputs[i];
      const settled = settledSearches[i];
      if (isNullish(searchJobInput) || isNullish(settled)) {
        continue;
      }
      const page = {
        backend: SearchBackend.Unique,
        query: job.input.search,
        mailbox: job.input.mailbox ?? undefined,
      };

      if (!searchJobInput.isScoped) {
        if (job.sourceCursorId) {
          pages.push({ ...page, status: SearchPageStatus.AccessRevoked });
        } else {
          summaries.push(
            `Semantic search "${job.input.search}" did not run: ${job.input.mailbox ?? 'the mailbox'} is not a mailbox you can access.`,
          );
        }
        continue;
      }
      if (searchJobInput.searchSummary) {
        summaries.push(searchJobInput.searchSummary);
      }

      if (settled.status === 'rejected') {
        traceError(settled.reason);
        pages.push({
          ...page,
          status: SearchPageStatus.Failed,
          continuation: this.toContinuation(job, job.page, job.seenChunkIds),
          retryCursorId: job.sourceCursorId,
        });
        continue;
      }

      const chunks = settled.value ?? [];
      const seen = new Set(job.seenChunkIds);
      const newChunks = chunks.filter((chunk) => !seen.has(chunk.chunkId));
      chunkLists.push(newChunks);
      pages.push({ ...page, ...this.getNextPosition(job, chunks.length === 0, newChunks) });
    }

    return {
      results: await this.buildResults(
        this.groupChunksByContent(chunkLists),
        context,
        userProfile,
        outputTimeZone,
      ),
      pages,
      searchSummary: summaries.length > 0 ? summaries.join('\r\n') : undefined,
    };
  }

  private getPageSize(job: SemanticPageJob): number {
    return job.input.limit ?? SEARCH_CONFIG.semanticSearch.defaultPageSize;
  }

  // Unique splits `limit` between a vector and a full-text search, pages each on its own and merges
  // them without duplicates, so a page usually holds fewer chunks than `limit` while more exist.
  // A chain ends on an empty page, or after `maxPages`: later pages only hold less relevant chunks.
  private getNextPosition(
    job: SemanticPageJob,
    isEmptyPage: boolean,
    newChunks: SearchResultItem[],
  ): Pick<BackendPage, 'status' | 'continuation'> {
    if (isEmptyPage || job.page >= SEARCH_CONFIG.semanticSearch.maxPages) {
      return { status: SearchPageStatus.Complete };
    }
    const seenChunkIds = unique([...job.seenChunkIds, ...newChunks.map(({ chunkId }) => chunkId)]);
    return {
      status: SearchPageStatus.HasMore,
      continuation: this.toContinuation(job, job.page + 1, seenChunkIds),
    };
  }

  private toContinuation(
    job: SemanticPageJob,
    page: number,
    seenChunkIds: string[],
  ): UniqueSearchCursorPayload {
    return { backend: SearchBackend.Unique, input: job.input, page, seenChunkIds };
  }

  // Merges the chunk lists of all searches by content. An email ranks by its best position in any
  // list.
  private groupChunksByContent(chunkLists: SearchResultItem[][]): AccumulatedContent[] {
    const accumulated = new Map<string, AccumulatedContent>();
    for (const chunks of chunkLists) {
      chunks.forEach((item, index) => {
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
    return Array.from(accumulated.values());
  }

  private async buildResults(
    contents: AccumulatedContent[],
    context: AccessContext,
    userProfile: NonNullishProps<UserProfile, 'email'>,
    outputTimeZone: string | undefined,
  ): Promise<SearchEmailResult[]> {
    const rawResults = pipe(
      contents,
      sortBy((item) => item.index),
      map((item): SearchEmailResult => {
        const metadata = item.content?.metadata as
          | (MessageMetadata & { folderIdPath?: string })
          | undefined;

        const sourceMailbox =
          context.mapUniqueFolderPathToOwnerEmail.find(({ uniqueFolderIdPath }) => {
            return metadata?.folderIdPath?.startsWith(uniqueFolderIdPath);
          })?.ownerEmail ?? null;

        const msGraphMessageId = metadata?.id || undefined;

        return {
          title: item.content.title ?? '',
          uniqueContentId: item.content.id,
          uniqueContentUrl: item.content.url ?? undefined,
          outlookWebLink: metadata?.webLink ?? '',
          sourceMailbox,
          msGraphMessageId,
          folderId: metadata?.parentFolderId ?? '',
          from: metadata?.fromEmailAddress ?? '',
          receivedDateTime:
            convertDateTimeToTimezone(metadata?.receivedDateTime, outputTimeZone) ?? '',
          backend: SearchBackend.Unique,
          text: concatChunks(Array.from(item.chunks.values())),
          openEmailParams: {
            id: item.content.id,
            idType: SearchBackend.Unique,
          },
          replyToParams: {
            ...(msGraphMessageId
              ? { inReplyToMessageId: msGraphMessageId, idIsImmutable: true }
              : {}),
            isReplyable: !!msGraphMessageId && metadata?.isDraft !== 'true',
          },
        };
      }),
    );

    // Semantic-backend IDs are always immutable. For delegated mailboxes the stored webLink may
    // use the new outlook.cloud.microsoft format (broken for some tenants) — translate the
    // immutable ID to a RestId and construct a working OWA URL.
    const buildWebLinksForIds = rawResults.flatMap((message) => {
      if (!message.msGraphMessageId || !message.sourceMailbox) {
        return [];
      }

      return [
        {
          id: message.msGraphMessageId,
          isImmutable: true,
          mailbox: message.sourceMailbox,
          webLink: message.outlookWebLink,
        },
      ];
    });

    const webLinksMap = await this.buildWebLinksCommand.run({
      userProfileId: userProfile.id,
      userProfileEmail: userProfile.email,
      ids: buildWebLinksForIds,
    });

    const results = rawResults.map((message) => {
      const outlookWebLink =
        message.msGraphMessageId && message.sourceMailbox
          ? (webLinksMap.get(webLinkMapKey(message.sourceMailbox, message.msGraphMessageId)) ?? '')
          : '';
      return {
        ...message,
        outlookWebLink,
      };
    });

    return results;
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
    input: SearchEmailsInput,
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
    conditions: SearchEmailsInput['conditions'];
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
