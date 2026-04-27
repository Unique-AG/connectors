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

  private formatText(semanticText: string | undefined, graphText: string | undefined): string {
    const sections: string[] = [];
    if (semanticText) {
      sections.push(`## Semantically Matched Content\n${semanticText}`);
    }
    if (graphText) {
      sections.push(`## Full Email Content Without Attachments\n${graphText}`);
    }
    return sections.join('\n\n');
  }

  private mergeResults(
    semanticResults: SearchEmailResult[],
    graphResults: SearchEmailResult[],
  ): SearchEmailResult[] {
    const graphById = new Map(graphResults.map((r) => [r.emailId, r]));

    const enriched: Array<{ result: SearchEmailResult; hadGraphMatch: boolean }> =
      semanticResults.map((semanticResult) => {
        const graphResult = graphById.get(semanticResult.emailId);
        if (graphResult) {
          graphById.delete(semanticResult.emailId);
          return {
            result: { ...semanticResult, text: this.formatText(semanticResult.text, graphResult.text) },
            hadGraphMatch: true,
          };
        }
        return { result: semanticResult, hadGraphMatch: false };
      });

    const top20 = enriched.slice(0, 20).map((e) => e.result);
    const remainder = enriched.slice(20);
    const commonRemainder = remainder.filter((e) => e.hadGraphMatch).map((e) => e.result);
    const semanticOnly = remainder.filter((e) => !e.hadGraphMatch).map((e) => e.result);

    const remainingGraph = Array.from(graphById.values()).map((graphResult) => ({
      ...graphResult,
      text: this.formatText(undefined, graphResult.text),
    }));

    return [...top20, ...commonRemainder, ...semanticOnly, ...remainingGraph];
  }
}
