import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import {
  buildKqlQueryString,
  graphSearchResponseSchema,
} from '~/features/content/search/ms-graph-kql-search-emails.query';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { SearchEmailResult } from '~/features/content/search/semantic-search-emails.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

@Injectable()
export class GraphSearchEmailsQuery {
  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(
    userProfileId: string,
    input: z.infer<typeof SearchEmailsInputSchema>,
  ): Promise<SearchEmailResult[]> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const queryString = buildKqlQueryString(input);
    const size = Math.min(input.limit ?? 25, 25);

    const raw = await client.api('/search/query').post({
      requests: [
        {
          entityTypes: ['message'],
          query: { queryString },
          enableTopResults: true,
          from: 0,
          size,
        },
      ],
    });

    const response = graphSearchResponseSchema.parse(raw);
    const hits = response.value[0]?.hitsContainers[0]?.hits ?? [];

    return hits.map((hit) => ({
      id: hit.resource.id,
      emailId: hit.resource.id,
      title: hit.resource.subject,
      from: hit.resource.from.emailAddress.address,
      receivedDateTime: hit.resource.receivedDateTime,
      text: hit.summary,
      outlookWebLink: hit.resource.webLink,
      folderId: hit.resource.parentFolderId,
      url: undefined,
    }));
  }
}
