import { Injectable } from '@nestjs/common';
import { isNullish } from 'remeda';
import * as z from 'zod';
import { GetMailboxTimezoneQuery } from '~/features/user-utils/get-mailbox-timezone.query';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { Nullish } from '~/utils/nullish';
import { MsGraphKqlSearchEmailsQuery } from './ms-graph-kql-search-emails.query';
import { SEARCH_CONFIG } from './search.config';
import { SearchEmailsInputSchema } from './search-conditions.dto';
import {
  SearchBackend,
  SearchEmailResult,
  SemanticSearchEmailsQuery,
} from './semantic-search-emails.query';

export interface SearchEmailsToolInput {
  uniqueSemanticSearchQueries?: z.infer<typeof SearchEmailsInputSchema>[];
  msGraphKeywordSearchQueries?: {
    mailbox?: Nullish<string>;
    kqlQuery: string;
    limit?: number;
  }[];
}

type BackendExecutor = (
  userProfileId: UserProfileTypeID,
  input: SearchEmailsToolInput,
  outputTimeZone: string | undefined,
) => Promise<{
  results: SearchEmailResult[];
  searchSummary: string | undefined;
}>;

@Injectable()
export class SearchEmailsQuery {
  public constructor(
    private readonly semanticSearchQuery: SemanticSearchEmailsQuery,
    private readonly msGraphKqlQuery: MsGraphKqlSearchEmailsQuery,
    private readonly getMailboxTimezoneQuery: GetMailboxTimezoneQuery,
  ) {}

  private readonly executors: Record<SearchBackend, BackendExecutor> = {
    [SearchBackend.Unique]: (
      userProfileId: UserProfileTypeID,
      input: SearchEmailsToolInput,
      outputTimeZone: string | undefined,
    ): Promise<{
      results: SearchEmailResult[];
      searchSummary: string | undefined;
    }> => {
      if (isNullish(SEARCH_CONFIG.semanticSearch) || !input.uniqueSemanticSearchQueries?.length) {
        return Promise.resolve({ results: [], searchSummary: undefined });
      }
      return this.semanticSearchQuery
        .run(userProfileId, input.uniqueSemanticSearchQueries, SEARCH_CONFIG.semanticSearch, outputTimeZone)
        .then(({ results, searchSummary }) => ({ results, searchSummary }));
    },
    [SearchBackend.MsGraph]: (
      userProfileId: UserProfileTypeID,
      input: SearchEmailsToolInput,
      outputTimeZone: string | undefined,
    ): Promise<{
      results: SearchEmailResult[];
      searchSummary: string | undefined;
    }> => {
      if (!input.msGraphKeywordSearchQueries) {
        return Promise.resolve({ results: [], searchSummary: undefined });
      }
      return this.msGraphKqlQuery.run(
        userProfileId,
        input.msGraphKeywordSearchQueries,
        SEARCH_CONFIG.msGraph,
        outputTimeZone,
      );
    },
  };

  public async run(
    userProfileId: UserProfileTypeID,
    input: SearchEmailsToolInput,
  ): Promise<{
    results: SearchEmailResult[];
    searchSummary: string | undefined;
  }> {
    const outputTimeZone = await this.getMailboxTimezoneQuery.run(userProfileId);

    const [
      { results: semanticResults, searchSummary: semanticSummary },
      { results: graphResults, searchSummary: graphSummary },
    ] = await Promise.all([
      this.executors[SearchBackend.Unique](userProfileId, input, outputTimeZone),
      this.executors[SearchBackend.MsGraph](userProfileId, input, outputTimeZone),
    ]);

    const summaries = [semanticSummary, graphSummary].filter((s): s is string => s !== undefined);
    const searchSummary = summaries.length > 0 ? summaries.join('\n\n') : undefined;

    return {
      results: this.mergeResults(semanticResults, graphResults),
      searchSummary,
    };
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
      sections.push(`## Full Email Content Without Attachments\n${graphText}`);
    }
    return sections.join('\n\n');
  }

  // We trust our semantic search more than KQL, so the top 20 semantic results are
  // anchored first. When Graph returned the same email, we enrich the semantic result
  // with the KQL body excerpt so the LLM sees both the attachment chunks and the full
  // email body.
  //
  // Beyond position 20 we treat a match in both backends as a stronger signal than a
  // semantic-only match, so common results are ranked above semantic-only stragglers.
  // Graph-only results come last as the weakest signal.
  //
  // Tier ordering (strongest → weakest confidence):
  //   1. Top-20 semantic results — anchored first, enriched with Graph body if available.
  //   2. Common remainder — matched by both backends but outside top-20.
  //   3. Semantic-only remainder — semantic match beyond top-20 with no Graph hit.
  //   4. Graph-only — lexical match with no semantic counterpart.
  //
  // Output is capped at 500 results to keep LLM context small.
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

    return [...topSemanticMatches, ...commonRemainder, ...semanticOnly, ...remainingGraph].slice(
      0,
      SEARCH_CONFIG.maxOutputEmails,
    );
  }
}
