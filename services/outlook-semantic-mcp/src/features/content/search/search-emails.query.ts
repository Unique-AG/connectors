import { Injectable } from '@nestjs/common';
import { omit, unique } from 'remeda';
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
import { SearchEmailsInput } from './search-conditions.dto';
import {
  SearchBackend,
  SearchEmailResult,
  SearchPage,
  SearchPageStatus,
} from './search-results.types';
import { SemanticSearchEmailsQuery } from './semantic-search-emails.query';

export interface SearchEmailsToolInput {
  uniqueSemanticSearchQueries?: SearchEmailsInput[];
  msGraphKeywordSearchQueries?: {
    mailbox?: Nullish<string>;
    kqlQuery: string;
    directories?: string[];
    limit?: number;
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

const EMPTY_BACKEND_OUTPUT: BackendOutput = { results: [], pages: [], searchSummary: undefined };

const isUniqueCursor = (
  cursor: StoredSearchCursor,
): cursor is StoredSearchCursor<UniqueSearchCursorPayload> =>
  cursor.payload.backend === SearchBackend.Unique;

const isMsGraphCursor = (
  cursor: StoredSearchCursor,
): cursor is StoredSearchCursor<MsGraphSearchCursorPayload> =>
  cursor.payload.backend === SearchBackend.MsGraph;

@Injectable()
export class SearchEmailsQuery {
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
    const semanticQueries = input.uniqueSemanticSearchQueries ?? [];
    const kqlQueries = input.msGraphKeywordSearchQueries ?? [];

    const [semantic, graph] = await Promise.all([
      !isMicrosoftGraphBackend() && semanticQueries.length
        ? this.semanticSearchQuery.run(userProfileId, semanticQueries, outputTimeZone)
        : EMPTY_BACKEND_OUTPUT,
      kqlQueries.length
        ? this.msGraphKqlQuery.run(userProfileId, kqlQueries, outputTimeZone)
        : EMPTY_BACKEND_OUTPUT,
    ]);

    return this.buildOutput(userProfileId, semantic, graph, []);
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
    const cursors = Array.from(storedCursors.values());
    const semanticCursors = cursors.filter(isUniqueCursor);
    const graphCursors = cursors.filter(isMsGraphCursor);
    const missingIds = requestedIds.filter((id) => !storedCursors.has(id));

    const outputTimeZone = await this.getMailboxTimezoneQuery.run(userProfileId);
    const [semantic, graph] = await Promise.all([
      semanticCursors.length
        ? this.semanticSearchQuery.fetchNextPages(userProfileId, semanticCursors, outputTimeZone)
        : EMPTY_BACKEND_OUTPUT,
      graphCursors.length
        ? this.msGraphKqlQuery.fetchNextPages(userProfileId, graphCursors, outputTimeZone)
        : EMPTY_BACKEND_OUTPUT,
    ]);

    const notes = missingIds.length
      ? [
          `The following cursors are unknown or expired: ${missingIds.join(', ')}. Run the search again to continue.`,
        ]
      : [];
    return this.buildOutput(userProfileId, semantic, graph, notes);
  }

  private async buildOutput(
    userProfileId: UserProfileTypeID,
    semantic: BackendOutput,
    graph: BackendOutput,
    additionalNotes: string[],
  ): Promise<SearchEmailsOutput> {
    const pages = await this.storeContinuations(userProfileId, [...semantic.pages, ...graph.pages]);
    const summaries = [semantic.searchSummary, graph.searchSummary, ...additionalNotes].filter(
      (summary): summary is string => summary !== undefined,
    );

    return {
      results: this.mergeResults(semantic.results, graph.results),
      pages,
      // Throttled and failed pages keep a cursor for a retry, but do not count: an agent that pages
      // until `hasMore` is false must not loop on a page that keeps failing.
      hasMore: pages.some(
        ({ status, cursorId }) => cursorId !== undefined && status === SearchPageStatus.HasMore,
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

  // We trust our semantic search more than KQL, so the top 20 semantic results are
  // anchored first. When Graph returned the same email, we enrich the semantic result
  // with the KQL body preview.
  //
  // Beyond position 20 we treat a match in both backends as a stronger signal than a
  // semantic-only match, so common results are ranked above semantic-only stragglers.
  // Graph-only results come last as the weakest signal.
  //
  // Tier ordering (strongest → weakest confidence):
  //   1. Top-20 semantic results — anchored first, enriched with Graph preview if available.
  //   2. Common remainder — matched by both backends but outside top-20.
  //   3. Semantic-only remainder — semantic match beyond top-20 with no Graph hit.
  //   4. Graph-only — lexical match with no semantic counterpart.
  //
  // Nothing is dropped: the response size is bounded by the page size of each backend request.
  private mergeResults(
    semanticResults: SearchEmailResult[],
    graphResults: SearchEmailResult[],
  ): SearchEmailResult[] {
    const graphById = new Map(
      graphResults
        .filter(
          (item): item is SearchEmailResult & { msGraphMessageId: string } =>
            !!item.msGraphMessageId,
        )
        .map((item) => [item.msGraphMessageId, item]),
    );

    const enriched: Array<{
      result: SearchEmailResult;
      hadGraphMatch: boolean;
    }> = semanticResults.map((semanticResult) => {
      const { msGraphMessageId } = semanticResult;
      const graphResult = msGraphMessageId ? graphById.get(msGraphMessageId) : null;

      if (!graphResult) {
        return { result: semanticResult, hadGraphMatch: false };
      }

      if (msGraphMessageId) {
        graphById.delete(msGraphMessageId);
      }
      return {
        result: {
          ...semanticResult,
          text: this.formatText({
            semanticText: semanticResult.text,
            graphText: graphResult.text,
          }),
          replyToParams: graphResult.replyToParams ?? semanticResult.replyToParams,
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
