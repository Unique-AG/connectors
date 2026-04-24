import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { SearchConditionSchema, SearchEmailsInputSchema } from './search-conditions.dto';
import { SearchEmailResult } from './search-emails.query';

function extractDatePart(isoDatetime: string): string {
  return isoDatetime.slice(0, 10);
}

function buildKqlForCondition(condition: z.infer<typeof SearchConditionSchema>): string {
  const parts: string[] = [];

  if (condition.dateFrom) {
    parts.push(`received>=${extractDatePart(condition.dateFrom.value)}`);
  }

  if (condition.dateTo) {
    parts.push(`received<=${extractDatePart(condition.dateTo.value)}`);
  }

  if (condition.fromSenders) {
    const field = condition.fromSenders;
    if (Array.isArray(field.value)) {
      if (field.operator === 'notIn') {
        // notIn is not supported in Graph Search KQL — skip silently
      } else {
        // in or containsAny
        const predicates = field.value.map((v) => `from:${v}`);
        if (predicates.length > 0) {
          parts.push(`(${predicates.join(' OR ')})`);
        }
      }
    } else {
      parts.push(`from:${field.value}`);
    }
  }

  if (condition.toRecipients) {
    const field = condition.toRecipients;
    if (Array.isArray(field.value)) {
      if (field.operator === 'notIn') {
        // notIn is not supported in Graph Search KQL — skip silently
      } else {
        const predicates = field.value.map((v) => `to:${v}`);
        if (predicates.length > 0) {
          parts.push(`(${predicates.join(' OR ')})`);
        }
      }
    } else {
      parts.push(`to:${field.value}`);
    }
  }

  if (condition.ccRecipients) {
    const field = condition.ccRecipients;
    if (Array.isArray(field.value)) {
      if (field.operator === 'notIn') {
        // notIn is not supported in Graph Search KQL — skip silently
      } else {
        const predicates = field.value.map((v) => `cc:${v}`);
        if (predicates.length > 0) {
          parts.push(`(${predicates.join(' OR ')})`);
        }
      }
    } else {
      parts.push(`cc:${field.value}`);
    }
  }

  if (condition.hasAttachments) {
    parts.push(`hasAttachment:${condition.hasAttachments.value}`);
  }

  if (condition.categories) {
    const field = condition.categories;
    if (Array.isArray(field.value)) {
      if (field.operator === 'notIn') {
        // notIn is not supported in Graph Search KQL — skip silently
      } else {
        const predicates = field.value.map((v) => `category:"${v}"`);
        if (predicates.length > 0) {
          parts.push(`(${predicates.join(' OR ')})`);
        }
      }
    } else {
      parts.push(`category:"${field.value}"`);
    }
  }

  // directories is not supported in Graph Search API KQL — skip silently

  return parts.join(' AND ');
}

export function buildKqlQueryString(input: z.infer<typeof SearchEmailsInputSchema>): string {
  const conditionGroups: string[] = [];

  for (const condition of input.conditions ?? []) {
    const kql = buildKqlForCondition(condition);
    if (kql) {
      conditionGroups.push(kql);
    }
  }

  if (conditionGroups.length === 0) {
    return input.search;
  }

  return `${input.search} AND ${conditionGroups.join(' AND ')}`;
}

interface GraphSearchHit {
  summary: string;
  resource: {
    id: string;
    subject: string;
    from: { emailAddress: { address: string } };
    receivedDateTime: string;
    parentFolderId: string;
    webLink: string;
  };
}

interface GraphSearchResponse {
  value: Array<{
    hitsContainers: Array<{
      hits?: GraphSearchHit[];
    }>;
  }>;
}

@Injectable()
export class GraphSearchEmailsQuery {
  constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  async run(
    userProfileId: string,
    input: z.infer<typeof SearchEmailsInputSchema>,
  ): Promise<SearchEmailResult[]> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const queryString = buildKqlQueryString(input);
    const size = Math.min(input.limit ?? 25, 25);

    const response: GraphSearchResponse = await client.api('/search/query').post({
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

    const hits = response?.value?.[0]?.hitsContainers?.[0]?.hits ?? [];

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
