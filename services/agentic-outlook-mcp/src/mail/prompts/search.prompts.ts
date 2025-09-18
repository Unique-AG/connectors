import { Prompt } from '@unique-ag/mcp-server-module';
import { Injectable, Scope } from '@nestjs/common';
import * as z from 'zod';

const LocateStatementsSchema = z.object({
  clientName: z.string().describe('Client name to search for').meta({ title: 'Client Name' }),
  since: z.string().optional().describe('Relative phrase or ISO date').meta({ title: 'Since' }),
});

const AttachmentTypeSchema = z.object({
  fileType: z
    .string()
    .describe('Attachment extension, e.g., pdf, xlsx')
    .meta({ title: 'File Type' }),
  dateFrom: z.string().describe('Relative phrase or ISO date from').meta({ title: 'Date From' }),
  dateTo: z.string().describe('Relative phrase or ISO date to').meta({ title: 'Date To' }),
});

const TickerDealSchema = z.object({
  keyword: z.string().describe('Ticker or deal code').meta({ title: 'Keyword' }),
  maxResults: z.string().describe('Max results').meta({ title: 'Max Results' }),
});

const MeetingInvitesSchema = z.object({
  clientName: z
    .string()
    .describe('Client name mentioned in invites')
    .meta({ title: 'Client Name' }),
  windowDays: z
    .string()
    .describe('Forward-looking window in days')
    .meta({ title: 'Window (Days)' }),
});

const PipelineDigestSchema = z.object({
  keyword: z.string().describe('Ticker or deal code').meta({ title: 'Keyword' }),
  period: z.string().describe("Time window, e.g., 'last 7 days'").meta({ title: 'Period' }),
});

const TopicSinceSchema = z.object({
  topic: z.string().describe('Topic to search for').meta({ title: 'Topic' }),
  since: z.string().describe('Relative phrase or ISO date').meta({ title: 'Since' }),
});

const NameSinceSchema = z.object({
  name: z.string().describe('Person name to search for').meta({ title: 'Name' }),
  since: z.string().describe('Relative phrase or ISO date').meta({ title: 'Since' }),
});

@Injectable({ scope: Scope.REQUEST })
export class SearchPrompts {
  @Prompt({
    name: 'search-locate-statements',
    title: 'Search: Locate Statements',
    description: 'Find latest client statement emails with summary fields',
    parameters: LocateStatementsSchema,
    _meta: {
      'unique.app/category': 'Search',
    },
  })
  public locateStatements({ clientName, since }: z.infer<typeof LocateStatementsSchema>) {
    return {
      description: 'Locate statement emails and return concise details',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Search for statement emails for ${clientName}${since ? ` since ${since}` : ''}. ` +
              `Use search-email, list-mails, and get-mail-message if needed. Return top 5 with subject, date, sender, attachment presence.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'search-attachments-type',
    title: 'Search: By Attachment Type',
    description: 'Find emails with a specific attachment type within a date range',
    parameters: AttachmentTypeSchema,
    _meta: {
      'unique.app/category': 'Search',
    },
  })
  public searchByAttachmentType({
    fileType,
    dateFrom,
    dateTo,
  }: z.infer<typeof AttachmentTypeSchema>) {
    return {
      description: 'Search emails by attachment file type and date range',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Search for emails with attachments of type ${fileType} between ${dateFrom} and ${dateTo}. ` +
              `Return messageId, subject, date, and sender. Use search-email and get-mail-message as needed.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'search-ticker-deal',
    title: 'Search: Ticker or Deal',
    description: 'Gather emails about a ticker or deal with snippets',
    parameters: TickerDealSchema,
    _meta: {
      'unique.app/category': 'Search',
    },
  })
  public searchTickerDeal({ keyword, maxResults }: z.infer<typeof TickerDealSchema>) {
    return {
      description: 'Compile a list of relevant emails about a ticker/deal',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text: `Search "${keyword}" and list up to ${maxResults} emails with short snippet summaries. Use search-email and list-mails.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'search-meeting-invites',
    title: 'Search: Meeting Invites',
    description: 'Locate upcoming calendar meeting invites referencing a client',
    parameters: MeetingInvitesSchema,
    _meta: {
      'unique.app/category': 'Search',
    },
  })
  public searchMeetingInvites({ clientName, windowDays }: z.infer<typeof MeetingInvitesSchema>) {
    return {
      description: 'Find invites for the specified client in the upcoming window',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Search for calendar invites referencing ${clientName} within the next ${windowDays} days. ` +
              `Return title, date, organizer, and messageId. Use search-email.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'triage-deal-pipeline-digest',
    title: 'Triage: Deal Pipeline Digest',
    description: 'Compile a digest of emails about a ticker/deal for a period',
    parameters: PipelineDigestSchema,
    _meta: {
      'unique.app/category': 'Triage',
    },
  })
  public dealPipelineDigest({ keyword, period }: z.infer<typeof PipelineDigestSchema>) {
    return {
      description: 'Provide grouped bullets for pipeline context',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Compile a digest of emails about "${keyword}" in ${period}. ` +
              `Group bullets by: mandates, diligence, legal, investor questions, risks. Use search-email and get-mail-message.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'search-topic-since',
    title: 'Search: Topic Since Date',
    description: 'Get all emails related to a topic since a relative phrase or date',
    parameters: TopicSinceSchema,
    _meta: {
      'unique.app/category': 'Search',
    },
  })
  public searchTopicSince({ topic, since }: z.infer<typeof TopicSinceSchema>) {
    return {
      description: 'Find emails about a topic since the provided date/relative period',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Search for emails related to "${topic}" since ${since}. Use search-email and list-mails. ` +
              `Return subject, date, sender, messageId, and a short snippet.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'search-name-since',
    title: 'Search: Name Since Date',
    description: 'Search emails for information about a person since a date/relative period',
    parameters: NameSinceSchema,
    _meta: {
      'unique.app/category': 'Search',
    },
  })
  public searchNameSince({ name, since }: z.infer<typeof NameSinceSchema>) {
    return {
      description: 'Find emails that mention or are from/to the person since the provided date',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Search for emails concerning ${name} since ${since}. Include from/to/cc matches and body mentions. ` +
              `Return subject, date, sender, messageId, and a short snippet.`,
          },
        },
      ],
    };
  }
}
