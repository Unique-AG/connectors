import { Injectable } from '@nestjs/common';
import * as z from 'zod';
import { mcpBackendSchema } from '~/config/app.config';
import { MsGraphKqlSearchEmailsQuery } from './ms-graph-kql-search-emails.query';
import {
  SearchBackend,
  SearchEmailResult,
  SemanticSearchEmailsQuery,
} from './semantic-search-emails.query';
import { SearchEmailsInputSchema } from './search-conditions.dto';

export type SearchEmailsToolInput = {
  semanticSearchParams?: z.infer<typeof SearchEmailsInputSchema>;
  msGraphSearchParams?: { queries: Array<{ kqlQuery: string; limit: number }> };
};

type McpBackend = z.infer<typeof mcpBackendSchema>;

type BackendExecutor = (
  userProfileId: string,
  input: SearchEmailsToolInput,
) => Promise<SearchEmailResult[]>;

const BACKENDS_FOR_CONFIG: Record<McpBackend, SearchBackend[]> = {
  MicrosoftGraph: [SearchBackend.MsGraph],
  MicrosoftGraphAndUniqueApi: [SearchBackend.Unique, SearchBackend.MsGraph],
};

@Injectable()
export class SearchEmailsQuery {
  public constructor(
    private readonly semanticSearchQuery: SemanticSearchEmailsQuery,
    private readonly msGraphKqlQuery: MsGraphKqlSearchEmailsQuery,
  ) {}

  private readonly executors: Record<SearchBackend, BackendExecutor> = {
    [SearchBackend.Unique]: (userProfileId, input) => {
      if (!input.semanticSearchParams) return Promise.resolve([]);
      return this.semanticSearchQuery
        .run(userProfileId, input.semanticSearchParams)
        .then(({ results }) => results);
    },
    [SearchBackend.MsGraph]: (userProfileId, input) => {
      if (!input.msGraphSearchParams) return Promise.resolve([]);
      return this.msGraphKqlQuery.run(userProfileId, input.msGraphSearchParams.queries);
    },
  };

  public async run(
    userProfileId: string,
    input: SearchEmailsToolInput,
  ): Promise<SearchEmailResult[]> {
    const mcpBackend = mcpBackendSchema.parse(process.env.MCP_BACKEND);
    const backendsToRun = BACKENDS_FOR_CONFIG[mcpBackend];

    const resultSets = await Promise.all(
      backendsToRun.map((backend) => this.executors[backend](userProfileId, input)),
    );

    return this.mergeResults(resultSets);
  }

  private mergeResults(resultSets: SearchEmailResult[][]): SearchEmailResult[] {
    const flat = resultSets.flat();
    const graphResults = flat.filter((r) => r.backend === SearchBackend.MsGraph);
    const uniqueResults = flat.filter((r) => r.backend === SearchBackend.Unique);

    const graphById = new Map(graphResults.map((r) => [r.emailId, r]));
    const uniqueOnly = uniqueResults.filter((r) => !graphById.has(r.emailId));

    // Graph results first (full body, better ranking), then Unique-only appended
    return [...graphResults, ...uniqueOnly];
  }
}
