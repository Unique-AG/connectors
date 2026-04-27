import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import {
  SearchBackend,
  SearchEmailResult,
} from '~/features/content/search/semantic-search-emails.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

const graphSearchHitSchema = z.object({
  summary: z.string(),
  resource: z.object({
    id: z.string(),
    subject: z.string(),
    from: z.object({ emailAddress: z.object({ address: z.string() }) }),
    receivedDateTime: z.string(),
    parentFolderId: z.string(),
    webLink: z.string(),
  }),
});

const graphSearchResponseSchema = z.object({
  value: z.array(
    z.object({
      hitsContainers: z.array(
        z.object({
          hits: z.array(graphSearchHitSchema).optional(),
        }),
      ),
    }),
  ),
});

@Injectable()
export class MsGraphKqlSearchEmailsQuery {
  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(
    userProfileId: string,
    queries: Array<{ kqlQuery: string; limit?: number }>,
  ): Promise<SearchEmailResult[]> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const allResults = await Promise.all(
      queries.map(async (query) => {
        const raw = await client.api('/search/query').post({
          requests: [
            {
              entityTypes: ['message'],
              query: { queryString: query.kqlQuery },
              enableTopResults: true,
              from: 0,
              size: Math.min(query.limit ?? 25, 50),
            },
          ],
        });
        const response = graphSearchResponseSchema.parse(raw);
        const hits = response.value[0]?.hitsContainers[0]?.hits ?? [];
        return hits.map((hit) => ({
          msGraphMessageId: hit.resource.id,
          emailId: hit.resource.id,
          title: hit.resource.subject,
          from: hit.resource.from.emailAddress.address,
          receivedDateTime: hit.resource.receivedDateTime,
          text: hit.summary,
          outlookWebLink: hit.resource.webLink,
          folderId: hit.resource.parentFolderId,
          uniqueContentUrl: undefined,
          backend: SearchBackend.MsGraph,
        }));
      }),
    );

    const seen = new Set<string>();
    const deduplicated: SearchEmailResult[] = [];
    for (const results of allResults) {
      for (const result of results) {
        if (!seen.has(result.emailId)) {
          seen.add(result.emailId);
          deduplicated.push(result);
        }
      }
    }

    return deduplicated;
  }
}
