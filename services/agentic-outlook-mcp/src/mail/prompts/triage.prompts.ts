import { Prompt } from '@unique-ag/mcp-server-module';
import { Injectable, Scope } from '@nestjs/common';
import * as z from 'zod';

const ThreadSummarySchema = z.object({
  threadQuery: z
    .string()
    .describe('Search terms, client name, or thread hint')
    .meta({ title: 'Thread Query' }),
  maxMessages: z.string().describe('Max messages to include').meta({ title: 'Max Messages' }),
});

const ExtractActionsSchema = z.object({
  messageId: z.string().describe('Email message ID to analyze').meta({ title: 'Message ID' }),
});

const ClassifyFolderSchema = z.object({
  messageId: z.string().describe('Email message ID to classify').meta({ title: 'Message ID' }),
  businessTaxonomy: z
    .string()
    .describe(
      "Business taxonomy, e.g., ['KYC','Onboarding','Trade Confirmations','RFP','Investor Relations']",
    )
    .meta({ title: 'Business Taxonomy' }),
});

const UrgencySlaSchema = z.object({
  messageId: z.string().describe('Email message ID to analyze').meta({ title: 'Message ID' }),
  slaPolicy: z
    .string()
    .describe('Policy string or JSON mapping category -> hours')
    .meta({ title: 'SLA Policy' }),
});

const UnreadAgingSchema = z.object({
  days: z.string().describe('Threshold in days').meta({ title: 'Days' }),
  folder: z.string().optional().describe('Optional folder scope').meta({ title: 'Folder' }),
});

@Injectable({ scope: Scope.REQUEST })
export class TriagePrompts {
  @Prompt({
    name: 'triage-summarize-thread',
    title: 'Triage: Summarize Thread',
    description: 'Summarize a client thread with actions, key dates, and risks',
    parameters: ThreadSummarySchema,
    _meta: {
      'unique.app/category': 'Triage',
    },
  })
  public summarizeThread({ threadQuery, maxMessages }: z.infer<typeof ThreadSummarySchema>) {
    return {
      description: 'Summarize the most relevant messages for a client/deal thread',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Summarize the thread for "${threadQuery}".\n` +
              `Plan: 1) search-email(query="${threadQuery}") to locate the best thread. 2) Pull up to ${maxMessages} messages in chronological order using list-mail-folder-messages or get-mail-message. 3) Output: ` +
              `Overview (3-5 bullets), Key dates, Decisions made, Open actions (assignee, due date), Risks/red flags, Next steps.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'triage-extract-action-items',
    title: 'Triage: Extract Action Items',
    description: 'Extract structured tasks and deadlines from a single email',
    parameters: ExtractActionsSchema,
    _meta: {
      'unique.app/category': 'Triage',
    },
  })
  public extractActionItems({ messageId }: z.infer<typeof ExtractActionsSchema>) {
    return {
      description: 'Extract tasks, owners, deadlines, dependencies from the email content',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Read message ${messageId} (use get-mail-message). Extract action items with fields: ` +
              `title, owner, deadline, dependencies, confidence (0-1), and source quotes. Return as a concise list.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'triage-classify-and-propose-folder',
    title: 'Triage: Classify and Propose Folder',
    description: 'Classify an email and propose a target folder based on business taxonomy',
    parameters: ClassifyFolderSchema,
    _meta: {
      'unique.app/category': 'Triage',
    },
  })
  public classifyAndProposeFolder({
    messageId,
    businessTaxonomy,
  }: z.infer<typeof ClassifyFolderSchema>) {
    return {
      description: 'Classify and propose a filing folder for the message',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Fetch ${messageId} (get-mail-message) and list available folders (list-mail-folders). ` +
              `Classify the message into the taxonomy: ${businessTaxonomy}. Propose a single best target folder with rationale and confidence.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'triage-urgency-sla',
    title: 'Triage: Determine Urgency and SLA',
    description: 'Determine urgency and SLA target for a message with justification',
    parameters: UrgencySlaSchema,
    _meta: {
      'unique.app/category': 'Triage',
    },
  })
  public determineUrgencySla({ messageId, slaPolicy }: z.infer<typeof UrgencySlaSchema>) {
    return {
      description: 'Assess urgency category and SLA using provided policy',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `Analyze message ${messageId} (get-mail-message). Assign urgency (Critical/High/Normal/Low), ` +
              `SLA target per policy ${slaPolicy}, and a brief justification referencing the text.`,
          },
        },
      ],
    };
  }

  @Prompt({
    name: 'triage-unread-aging',
    title: 'Triage: Unread Older Than N Days',
    description: 'List unread emails older than N days with brief reason-to-open',
    parameters: UnreadAgingSchema,
    _meta: {
      'unique.app/category': 'Triage',
    },
  })
  public listUnreadAging({ days, folder }: z.infer<typeof UnreadAgingSchema>) {
    const scope = folder ? ` in folder "${folder}"` : '';
    return {
      description: 'Identify stale unread emails for triage',
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text:
              `List unread emails older than ${days} days${scope}. ` +
              `Use list-mails and/or search-email as needed. Sort by age desc. Include subject, sender, date, and a one-line reason-to-open.`,
          },
        },
      ],
    };
  }
}
