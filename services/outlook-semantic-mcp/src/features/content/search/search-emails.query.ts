import { Injectable } from '@nestjs/common';
import { omit, sum, unique } from 'remeda';
import { GetMailboxTimezoneQuery } from '~/features/user-utils/get-mailbox-timezone.query';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { Nullish } from '~/utils/nullish';
import {
  BackendPage,
  MsGraphSearchCursorPayload,
  StoredSearchCursor,
  UniqueSearchCursorPayload,
} from './cursors/search-cursor.payload';
import { SearchCursorRepository } from './cursors/search-cursor.repository';
import { MsGraphKqlSearchEmailsQuery } from './ms-graph-kql-search-emails.query';
import { SEARCH_CONFIG } from './search.config';
import { SearchEmailsInput } from './search-conditions.dto';
import {
  SearchBackend,
  SearchEmailResult,
  SearchPage,
  SearchPageStatus,
} from './search-results.types';
import { SemanticSearchEmailsQuery } from './semantic-search-emails.query';

@Injectable()
export class SearchEmailsQuery {
  private readonly EMPTY_BACKEND_OUTPUT: BackendOutput = {
    results: [],
    pages: [],
    searchSummary: undefined,
  };

  public constructor(
    private readonly semanticSearchQuery: SemanticSearchEmailsQuery,
    private readonly msGraphKqlQuery: MsGraphKqlSearchEmailsQuery,
    private readonly getMailboxTimezoneQuery: GetMailboxTimezoneQuery,
    private readonly searchCursorRepository: SearchCursorRepository,
  ) {}

  public async run(
    userProfileId: UserProfileTypeID,
    input: SearchEmailsToolInput,
  ): Promise<SearchEmailsOutput> {
    const outputTimeZone = await this.getMailboxTimezoneQuery.run(userProfileId);
    const semanticQueries = isMicrosoftGraphBackend()
      ? []
      : (input.uniqueSemanticSearchQueries ?? []);
    const kqlQueries = input.msGraphKeywordSearchQueries ?? [];

    // Every query gets an equal share of the response budget. A semantic search uses its share as
    // its page size. The KQL queries pool what the semantic searches leave and split it across
    // their mailboxes and folders.
    const { maxResultsPerResponse, maxPageSize } = SEARCH_CONFIG;
    const share = Math.floor(
      maxResultsPerResponse / Math.max(1, semanticQueries.length + kqlQueries.length),
    );
    const semanticPageSize = Math.min(maxPageSize, share);
    const graphBudget = maxResultsPerResponse - semanticQueries.length * semanticPageSize;

    const [semantic, graph] = await Promise.all([
      semanticQueries.length
        ? this.semanticSearchQuery.run(
            userProfileId,
            semanticQueries,
            outputTimeZone,
            semanticPageSize,
          )
        : this.EMPTY_BACKEND_OUTPUT,
      kqlQueries.length
        ? this.msGraphKqlQuery.run(userProfileId, kqlQueries, outputTimeZone, graphBudget)
        : this.EMPTY_BACKEND_OUTPUT,
    ]);

    return this.buildOutput(userProfileId, semantic, graph, [], []);
  }

  public async fetchNextPages(
    userProfileId: UserProfileTypeID,
    cursorIds: string[],
  ): Promise<SearchEmailsOutput> {
    const requestedIds = unique(cursorIds);
    const storedCursors = await this.searchCursorRepository.findForUser(
      userProfileId.toString(),
      requestedIds,
    );
    const cursors = requestedIds.flatMap((id) => storedCursors.get(id) ?? []);
    const fetchedCount = this.countCursorsWithinBudget(cursors);
    const fetchedCursors = cursors.slice(0, fetchedCount);
    const semanticCursors = fetchedCursors.filter((cursor) => this.isUniqueCursor(cursor));
    const graphCursors = fetchedCursors.filter((cursor) => this.isMsGraphCursor(cursor));
    const missingIds = requestedIds.filter((id) => !storedCursors.has(id));

    const outputTimeZone = await this.getMailboxTimezoneQuery.run(userProfileId);
    const [semantic, graph] = await Promise.all([
      semanticCursors.length
        ? this.semanticSearchQuery.fetchNextPages(userProfileId, semanticCursors, outputTimeZone)
        : this.EMPTY_BACKEND_OUTPUT,
      graphCursors.length
        ? this.msGraphKqlQuery.fetchNextPages(userProfileId, graphCursors, outputTimeZone)
        : this.EMPTY_BACKEND_OUTPUT,
    ]);

    const notes = missingIds.length
      ? [
          `The following cursors are unknown or expired: ${missingIds.join(', ')}. Run the search again to continue.`,
        ]
      : [];
    return this.buildOutput(
      userProfileId,
      semantic,
      graph,
      notes,
      cursors.slice(fetchedCount).map((cursor) => this.toDeferredPage(cursor)),
    );
  }

  private isUniqueCursor(
    cursor: StoredSearchCursor,
  ): cursor is StoredSearchCursor<UniqueSearchCursorPayload> {
    return cursor.payload.backend === SearchBackend.Unique;
  }

  private isMsGraphCursor(
    cursor: StoredSearchCursor,
  ): cursor is StoredSearchCursor<MsGraphSearchCursorPayload> {
    return cursor.payload.backend === SearchBackend.MsGraph;
  }

  // How many of the cursors, in the order requested, fit the response budget.
  private countCursorsWithinBudget(cursors: StoredSearchCursor[]): number {
    const pageSizes = cursors.map(({ payload }) => payload.pageSize);
    return pageSizes.filter(
      (_, i) => sum(pageSizes.slice(0, i + 1)) <= SEARCH_CONFIG.maxResultsPerResponse,
    ).length;
  }

  private toDeferredPage({ id, payload }: StoredSearchCursor): BackendPage {
    return {
      ...(payload.backend === SearchBackend.MsGraph
        ? {
            backend: payload.backend,
            query: payload.kqlQuery,
            mailbox: payload.mailbox,
            folder: payload.folderName,
          }
        : {
            backend: payload.backend,
            query: payload.input.search,
            mailbox: payload.input.mailbox ?? undefined,
          }),
      status: SearchPageStatus.Deferred,
      retryCursorId: id,
    };
  }

  private async buildOutput(
    userProfileId: UserProfileTypeID,
    semantic: BackendOutput,
    graph: BackendOutput,
    additionalNotes: string[],
    deferredPages: BackendPage[],
  ): Promise<SearchEmailsOutput> {
    const pages = await this.storeContinuations(userProfileId, [
      ...semantic.pages,
      ...graph.pages,
      ...deferredPages,
    ]);
    const summaries = [semantic.searchSummary, graph.searchSummary, ...additionalNotes].filter(
      (summary): summary is string => summary !== undefined,
    );

    return {
      results: this.mergeResults(semantic.results, graph.results),
      pages,
      // Throttled and failed pages keep a cursor for a retry, but do not count: an agent that pages
      // until `hasMore` is false must not loop on a page that keeps failing.
      hasMore: pages.some(
        ({ status, cursorId }) =>
          cursorId !== undefined &&
          (status === SearchPageStatus.HasMore || status === SearchPageStatus.Deferred),
      ),
      searchSummary: summaries.length > 0 ? summaries.join('\n\n') : undefined,
    };
  }

  // Pages fetched from a cursor that must be retried keep that cursor's id. Every other
  // continuation becomes a new immutable cursor row.
  private async storeContinuations(
    userProfileId: UserProfileTypeID,
    backendPages: BackendPage[],
  ): Promise<SearchPage[]> {
    const toStore = backendPages.flatMap((page, pageIndex) =>
      page.continuation && !page.retryCursorId
        ? [{ pageIndex, continuation: page.continuation }]
        : [],
    );
    const newIds = await this.searchCursorRepository.create(
      userProfileId.toString(),
      toStore.map(({ continuation }) => continuation),
    );
    const newIdByPageIndex = new Map(toStore.map(({ pageIndex }, i) => [pageIndex, newIds[i]]));

    return backendPages.map((page, pageIndex) => ({
      ...omit(page, ['continuation', 'retryCursorId']),
      cursorId: page.retryCursorId ?? newIdByPageIndex.get(pageIndex),
    }));
  }

  private formatText({
    semanticText,
    graphText,
  }: {
    semanticText?: string;
    graphText?: string;
  }): string {
    const sections: string[] = [];
    if (semanticText) {
      sections.push(`## Semantically Matched Content\n${semanticText}`);
    }
    if (graphText) {
      sections.push(`## Preview\n${graphText}`);
    }
    return sections.join('\n\n');
  }

  // Order: top-20 semantic (enriched with the Graph preview when both matched), then other matches
  // of both backends, then semantic-only, then Graph-only. Nothing is dropped.
  private mergeResults(
    semanticResults: SearchEmailResult[],
    graphResults: SearchEmailResult[],
  ): SearchEmailResult[] {
    const graphById = new Map(graphResults.map((item) => [item.msGraphMessageId, item]));

    const enriched: Array<{
      result: SearchEmailResult;
      hadGraphMatch: boolean;
    }> = semanticResults.map((semanticResult) => {
      const graphResult = graphById.get(semanticResult.msGraphMessageId);

      if (!graphResult) {
        return { result: semanticResult, hadGraphMatch: false };
      }

      graphById.delete(semanticResult.msGraphMessageId);
      return {
        result: {
          ...semanticResult,
          text: this.formatText({
            semanticText: semanticResult.text,
            graphText: graphResult.text,
          }),
          replyToParams: graphResult.replyToParams ?? semanticResult.replyToParams,
          isDraft: graphResult.isDraft,
          openEmailParams: {
            ...graphResult.openEmailParams,
            ...(semanticResult.openEmailParams.uniqueContentId
              ? { uniqueContentId: semanticResult.openEmailParams.uniqueContentId }
              : {}),
            ...(semanticResult.openEmailParams.chunkIds
              ? { chunkIds: semanticResult.openEmailParams.chunkIds }
              : {}),
          },
        },
        hadGraphMatch: true,
      };
    });

    const topSemanticMatches = enriched.slice(0, 20).map((e) => e.result);
    const remainder = enriched.slice(20);
    const commonRemainder = remainder.filter((e) => e.hadGraphMatch).map((e) => e.result);
    const semanticOnly = remainder.filter((e) => !e.hadGraphMatch).map((e) => e.result);

    const remainingGraph = Array.from(graphById.values()).map((graphResult) => ({
      ...graphResult,
      text: this.formatText({ graphText: graphResult.text }),
    }));

    return [...topSemanticMatches, ...commonRemainder, ...semanticOnly, ...remainingGraph];
  }
}

export interface SearchEmailsToolInput {
  uniqueSemanticSearchQueries?: SearchEmailsInput[];
  msGraphKeywordSearchQueries?: {
    mailbox?: Nullish<string>;
    kqlQuery: string;
    directories?: string[];
  }[];
}

export interface SearchEmailsOutput {
  results: SearchEmailResult[];
  pages: SearchPage[];
  hasMore: boolean;
  searchSummary: string | undefined;
}

interface BackendOutput {
  results: SearchEmailResult[];
  pages: BackendPage[];
  searchSummary: string | undefined;
}
