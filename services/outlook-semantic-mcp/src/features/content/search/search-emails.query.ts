import { Injectable } from '@nestjs/common';
import * as z from 'zod';
import { MsGraphKqlSearchEmailsQuery } from './ms-graph-kql-search-emails.query';
import { SearchEmailsInputSchema } from './semantic-search-conditions.dto';
import {
  SearchBackend,
  SearchEmailResult,
  SemanticSearchEmailsQuery,
} from './semantic-search-emails.query';

export interface SearchEmailsToolInput {
  semanticSearchParams?: z.infer<typeof SearchEmailsInputSchema>;
  msGraphSearchParams?: { queries: Array<{ kqlQuery: string; limit?: number }> };
}

type BackendExecutor = (
  userProfileId: string,
  input: SearchEmailsToolInput,
) => Promise<SearchEmailResult[]>;

@Injectable()
export class SearchEmailsQuery {
  public constructor(
    private readonly semanticSearchQuery: SemanticSearchEmailsQuery,
    private readonly msGraphKqlQuery: MsGraphKqlSearchEmailsQuery,
  ) {}

  private readonly executors: Record<SearchBackend, BackendExecutor> = {
    [SearchBackend.Unique]: (
      userProfileId: string,
      input: SearchEmailsToolInput,
    ): Promise<SearchEmailResult[]> => {
      if (!input.semanticSearchParams) {
        return Promise.resolve([]);
      }
      return this.semanticSearchQuery
        .run(userProfileId, input.semanticSearchParams)
        .then(({ results }) => results);
    },
    [SearchBackend.MsGraph]: (
      userProfileId: string,
      input: SearchEmailsToolInput,
    ): Promise<SearchEmailResult[]> => {
      if (!input.msGraphSearchParams) {
        return Promise.resolve([]);
      }
      return this.msGraphKqlQuery.run(userProfileId, input.msGraphSearchParams.queries);
    },
  };

  public async run(
    userProfileId: string,
    input: SearchEmailsToolInput,
  ): Promise<SearchEmailResult[]> {
    const [semanticResults, graphResults] = await Promise.all([
      this.executors[SearchBackend.Unique](userProfileId, input),
      this.executors[SearchBackend.MsGraph](userProfileId, input),
    ]);

    return this.mergeResults(semanticResults, graphResults);
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

    const enriched: Array<{ result: SearchEmailResult; hadGraphMatch: boolean }> =
      semanticResults.map((semanticResult) => {
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
    const remainder = enriched.slice(topSemanticMatches.length);
    const commonRemainder = remainder.filter((e) => e.hadGraphMatch).map((e) => e.result);
    const semanticOnly = remainder.filter((e) => !e.hadGraphMatch).map((e) => e.result);

    const remainingGraph = Array.from(graphById.values()).map((graphResult) => ({
      ...graphResult,
      text: this.formatText({ graphText: graphResult.text }),
    }));

    return [...topSemanticMatches, ...commonRemainder, ...semanticOnly, ...remainingGraph].slice(
      0,
      500,
    );
  }
}
