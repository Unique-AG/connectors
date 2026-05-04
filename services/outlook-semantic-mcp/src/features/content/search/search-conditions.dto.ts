import { UniqueQLOperator } from '@unique-ag/unique-api';
import { z } from 'zod';
import { clampToValidDate } from '~/utils/clamp-to-valid-date';

export const CONTAINS_ANY_OPERATOR = 'containsAny' as const;

// Note: We have 2 array functions because if we use an options parameter it seems typescript
// does not infer the types correctly.

// Used for fields where containsAny partial matching is meaningful (e.g. email addresses).
const ArrayConditionFieldSchema = <T extends z.ZodArray>(itemSchema: T) =>
  z.object({
    value: itemSchema,
    operator: z.enum([UniqueQLOperator.IN, UniqueQLOperator.NOT_IN, CONTAINS_ANY_OPERATOR]),
  });

// Used for fields where only exact equality makes sense (e.g. folder IDs / directory names),
// so containsAny is excluded to avoid misleading the LLM into substring-matching opaque IDs.
const StrictArrayConditionFieldSchema = <T extends z.ZodArray>(itemSchema: T) =>
  z.object({
    value: itemSchema,
    operator: z.enum([UniqueQLOperator.IN, UniqueQLOperator.NOT_IN]),
  });

const SingularConditionFieldSchema = <T extends z.ZodTypeAny>(valueSchema: T) =>
  z.object({
    value: valueSchema,
    operator: z.enum([
      UniqueQLOperator.EQUALS,
      UniqueQLOperator.NOT_EQUALS,
      UniqueQLOperator.GREATER_THAN,
      UniqueQLOperator.GREATER_THAN_OR_EQUAL,
      UniqueQLOperator.LESS_THAN,
      UniqueQLOperator.LESS_THAN_OR_EQUAL,
      UniqueQLOperator.CONTAINS,
      UniqueQLOperator.NOT_CONTAINS,
      UniqueQLOperator.IS_NULL,
      UniqueQLOperator.IS_NOT_NULL,
      UniqueQLOperator.IS_EMPTY,
      UniqueQLOperator.IS_NOT_EMPTY,
    ]),
  });

const EXAMPLE_FOLDER_IDS = {
  first:
    'AQMkADllMDJjNDk0LWNiNmEtNDhlOC04YjA4LWMzNDZlOTkANzlhMmMALgAAA8XAUl8fmjpEkM39lOfyshYBAMjQHeJoK_1Bt2gTZjb69YQAAAIBCAAAAA==',
  second:
    'AQMkADllMDJjNDk0LWNiNmEtNDhlOC04YjA4LWMzNDZlOTkANzlhMmMALgAAA8XAUl8fmjpEkM39lOfyshYBAMjQHeJoK_1Bt2gTZjb69YQAAAIBWQAAAA==',
};

// z.string() instead of z.email() to allow partial inputs like domains ("@example.com")
// that are valid for contains/containsAny matching but not strict email addresses.
const emailConditionsSchema = (label: string) =>
  SingularConditionFieldSchema(
    z
      .string()
      .describe(
        `${label} email address or domain to filter by. To match a specific address use equals: "alice@example.com". To match all senders from a domain use contains with just the domain name: "google.com" (do NOT use "@google.com" — that will never match). Recommended operators: equals, contains, notContains.`,
      ),
  )
    .or(
      ArrayConditionFieldSchema(
        z
          .array(z.string())
          .describe(
            `List of ${label.toLowerCase()} emails or domains. Use containsAny for partial/domain matching — e.g. ["google.com", "microsoft.com"] matches all senders from those domains. Use in/notIn for exact full-address matching only — e.g. ["alice@example.com"]. Never use in with partial values like "@google.com" — use containsAny or the singular contains form instead.`,
          ),
      ),
    )
    .optional();

const clampedDatetime = z.preprocess(
  clampToValidDate,
  z.iso.datetime({ message: 'Must be UTC ISO 8601 format, e.g. "2024-01-01T00:00:00Z"' }),
);

export const SearchConditionSchema = z
  .object({
    dateFrom: SingularConditionFieldSchema(
      clampedDatetime.describe(
        'Filter emails received on or after this date. UTC ISO 8601 format, e.g. "2024-01-01T00:00:00Z". ' +
          'Must be a valid calendar date — February has 28 days in non-leap years (e.g. use "2026-02-28", not "2026-02-29"). ' +
          'Recommended operators: greaterThanOrEqual, greaterThan.',
      ),
    ).optional(),
    dateTo: SingularConditionFieldSchema(
      clampedDatetime.describe(
        'Filter emails received on or before this date. UTC ISO 8601 format, e.g. "2024-12-31T23:59:59Z". ' +
          'Must be a valid calendar date — February has 28 days in non-leap years (e.g. use "2026-02-28T23:59:59Z", not "2026-02-29T23:59:59Z"). ' +
          'Recommended operators: lessThanOrEqual, lessThan.',
      ),
    ).optional(),
    fromSenders: emailConditionsSchema('Sender'),
    toRecipients: emailConditionsSchema('To recipient'),
    ccRecipients: emailConditionsSchema('CC recipient'),
    directories: StrictArrayConditionFieldSchema(
      z
        .array(z.string())
        .describe(
          `Folder ID(s) or system directory name(s) to filter by. ` +
            `For well-known Outlook system folders pass the exact display name directly — no need to call \`list_folders\`: ` +
            `"Inbox", "Sent Items", "Drafts", "Archive", "Outbox", "Clutter", "Conversation History". ` +
            `Note: "Deleted Items", "Junk Email", and "Recoverable Items Deletions" are not synchronized and will not return results. ` +
            `For custom user-defined folders, pass the folder ID obtained from \`list_folders\`. ` +
            `Example IDs: ["${EXAMPLE_FOLDER_IDS.first}", "${EXAMPLE_FOLDER_IDS.second}"]. Recommended operators: in or notIn.`,
        ),
    ).optional(),
    hasAttachments: SingularConditionFieldSchema(
      z
        .enum(['true', 'false'])
        .describe(
          `Whether the email has attachments, e.g. 'true' or 'false'. This value is a string not a boolean. Recommended operator: equals, notEquals.`,
        ),
    ).optional(),
    categories: SingularConditionFieldSchema(
      z
        .string()
        .describe(
          `Category label(s) to filter by, e.g. "Important". Categories can be found using \`list_categories\` tool. Recommended operators: equals or contains.`,
        ),
    )
      .or(
        ArrayConditionFieldSchema(
          z
            .array(z.string())
            .describe(
              `Category label(s) to filter by, e.g. ["Important", "Project-X"]. Categories can be found using \`list_categories\` tool. Recommended operators: in or notIn.`,
            ),
        ),
      )
      .optional(),
  })
  .refine((obj) => Object.values(obj).some((v) => v !== undefined), {
    message: `Invalid search condition, the following fields are supported for conditions 'dateFrom', 'dateTo', 'fromSenders', 'toRecipients', 'ccRecipients', 'directories', 'hasAttachments', 'categories'. Example of valid condition: { fromSenders: { value: "alice@example.com", operator: "equals" } }`,
  })
  .describe(
    `Condition to narrow down the search, AND operator is applied between multiple conditions fields`,
  );

export type SearchCondition = z.infer<typeof SearchConditionSchema>;

export const SearchEmailsInputSchema = z.object({
  search: z
    .string()
    .nonempty()
    .describe('Search query, e.g. "quarterly report from Alice" or "meeting invitation next week"'),
  mailbox: z
    .email()
    .describe(
      `Scope this entire search to one mailbox (exact email address match, no wildcards). ` +
        `When omitted, all accessible mailboxes (own + delegated) are searched. ` +
        `Use the \`list_folders\` tool to discover which mailboxes are available for the current user.`,
    )
    .optional(),
  conditions: z
    .array(SearchConditionSchema)
    .optional()
    .describe(
      `Conditions to narrow down the search, If we pass multiple conditions we apply OR operator between them.`,
    ),
  limit: z
    .number()
    .int()
    .min(150)
    .max(300)
    .optional()
    .prefault(200)
    .describe(
      [
        'Maximum number of results to return. Must be between 150 and 300.',
        'If the search query is targeted (e.g. looking for a specific email or thread), pass 150 (the minimum).',
        'If the query is fuzzy or broad (e.g. "overview of all emails from alice@example.com", "list emails from last week", "what happened last week"), pick a limit between 200 and 300.',
        'When the expected result set is large, always use 300.',
      ].join(' '),
    ),
});

export type SearchEmailsInput = z.infer<typeof SearchEmailsInputSchema>;

export const MsGraphKqlQuerySchema = z.object({
  mailbox: z
    .email()
    .optional()
    .describe(
      'Scope this KQL query to a specific mailbox (exact email address). When omitted, searches the current user\'s primary mailbox. Note: Microsoft Graph KQL search does not support delegated-access mailboxes — only the current user\'s own mailbox is searchable.',
    ),
  kqlQuery: z
    .string()
    .nonempty()
    .describe(
      'KQL (Keyword Query Language) query string for Microsoft Graph email search.\n' +
        'Supported property filters:\n' +
        '  from:<email>              — sender address (exact or domain, e.g. from:alice@example.com)\n' +
        '  to:<email>                — recipient in To field\n' +
        '  cc:<email>                — recipient in CC field\n' +
        '  subject:<words>           — words in the subject line (phrase: subject:"budget report")\n' +
        '  body:<words>              — words in the message body\n' +
        '  received>=YYYY-MM-DD      — received on or after date\n' +
        '  received<=YYYY-MM-DD      — received on or before date\n' +
        '  hasAttachment:true/false  — whether the email has attachments\n' +
        '  category:"label"          — Outlook category label\n' +
        'Free-text terms (no property prefix) perform a full-text search across subject and body.\n' +
        'Combine clauses with AND / OR; use double quotes for phrases.\n' +
        'Examples:\n' +
        '  "from:alice@example.com subject:\\"Q2 budget\\" received>=2024-01-01"\n' +
        '  "project proposal hasAttachment:true received>=2024-03-01 received<=2024-03-31"\n' +
        '  "from:hr@acme.com OR from:payroll@acme.com subject:salary"',
    ),
  limit: z
    .number()
    .int()
    .min(1)
    .max(50)
    .optional()
    .prefault(25)
    .describe(
      'Maximum number of results to return for this query. Must be between 1 and 50. Default is 25. Use a higher value (up to 50) for broad or exploratory queries; the default is sufficient for targeted searches.',
    ),
});

export const MsGraphSearchParamsSchema = z
  .array(MsGraphKqlQuerySchema)
  .min(1)
  .max(20)
  .describe('List of KQL queries to execute in parallel. Maximum 20.');

export const SearchEmailsMsGraphInputSchema = z.object({
  msGraphKeywordSearchQueries: MsGraphSearchParamsSchema,
});

export const SearchEmailsUnifiedInputSchema = z
  .object({
    uniqueSemanticSearchQueries: z
      .array(SearchEmailsInputSchema)
      .min(1)
      .max(10)
      .describe(
        'List of semantic searches to execute in parallel (at most 10). ALL entries must address the SAME single user question — do NOT pack unrelated questions into this array. ' +
          'Use multiple entries only to approach the same question from different angles ' +
          '(e.g. trying different phrasings, synonyms, or narrower vs. broader terms for the same intent). ' +
          'IMPORTANT: uniqueSemanticSearchQueries supports delegated-access mailboxes — use the mailbox field to scope searches to specific mailboxes including delegated ones. ' +
          'Results from all searches are merged and deduplicated by email ID.',
      ),
    msGraphKeywordSearchQueries: MsGraphSearchParamsSchema.optional().describe(
      'KQL queries that address the SAME single user question as uniqueSemanticSearchQueries, expressed using keyword/lexical search. ' +
        'Use multiple entries to approach the same question from different angles (e.g. different keyword combinations, subject vs. body focus). ' +
        "IMPORTANT: Microsoft Graph keyword search does NOT support delegated-access mailboxes — it only searches the current user's own mailbox. " +
        'When provided, results from both backends are merged: semantic results are anchored first ' +
        'and enriched with the Graph body excerpt when the same email was matched by both. ' +
        'Always try to fill this alongside uniqueSemanticSearchQueries — the combined result gives a ' +
        'more complete picture than either search alone.',
    ),
  })
  .describe(
    'IMPORTANT: uniqueSemanticSearchQueries and msGraphKeywordSearchQueries must both address the SAME single user question — ' +
      'each using its own query language and approaching the question from different angles. ' +
      'Do NOT spread multiple unrelated user questions across the two fields. ' +
      'The two searches run in parallel and their results are merged to provide a broader and more reliable overview: ' +
      'semantic search covers natural-language relevance, attachment content, and delegated-access mailboxes; ' +
      'KQL covers lexical precision and full email-body excerpts (own mailbox only, no delegated access).',
  );
