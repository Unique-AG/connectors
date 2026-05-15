import { UniqueQLOperator } from '@unique-ag/unique-api';
import { z } from 'zod';
import { clampToValidDate } from '~/utils/clamp-to-valid-date';
import { SEARCH_CONFIG } from './search.config';

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
            `For well-known Outlook system folders pass the exact display name directly — no need to call \`list_mailboxes_and_directories\`: ` +
            `"Inbox", "Sent Items", "Drafts", "Archive", "Outbox", "Clutter", "Conversation History". ` +
            `Note: "Deleted Items", "Junk Email", and "Recoverable Items Deletions" are not synchronized and will not return results. ` +
            `For custom user-defined folders, pass the folder ID obtained from \`list_mailboxes_and_directories\`. ` +
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
    `Structured filter applied on top of the semantic search. Lean toward populating this when the user clearly names a specific sender, recipient, date range, folder, attachment requirement, or category — populated conditions tend to produce sharper results than relying on the natural-language \`search\` text alone. If a signal is ambiguous, prefer omitting the condition over guessing. Fields within a single condition are AND-ed. Example: user says "from alice@x.com last month" → { fromSenders: { value: "alice@x.com", operator: "equals" }, dateFrom: { value: "2026-04-01T00:00:00Z", operator: "greaterThanOrEqual" } }.`,
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
        `Use the \`list_mailboxes_and_directories\` tool to discover which mailboxes are available for the current user.`,
    )
    .optional(),
  conditions: z
    .array(SearchConditionSchema)
    .optional()
    .describe(
      `Structured filters applied on top of the semantic search. Prefer populating this when the user clearly names a specific sender, recipient, date, folder, attachment requirement, or category — these signals tend to produce sharper results when expressed structurally rather than only in the natural-language \`search\` text. Omit a condition rather than guess if the signal is ambiguous. Each entry in this array is OR-ed with the others; fields within a single entry are AND-ed. Example: user says "from alice@x.com" → [{ fromSenders: { value: "alice@x.com", operator: "equals" } }].`,
    ),
  limit: z
    .number()
    .int()
    .min(SEARCH_CONFIG.semanticSearch?.subQueryChunksLimits.min ?? 0)
    .max(SEARCH_CONFIG.semanticSearch?.subQueryChunksLimits.max ?? 0)
    .optional()
    .prefault(SEARCH_CONFIG.semanticSearch?.subQueryChunksLimits.default ?? 0)
    .describe(SEARCH_CONFIG.semanticSearch?.subQueryChunksLimits.description ?? ''),
});

export type SearchEmailsInput = z.infer<typeof SearchEmailsInputSchema>;

export const MsGraphKqlQuerySchema = z.object({
  mailbox: z
    .email()
    .describe(
      `Scope this entire search to one mailbox (exact email address match, no wildcards). ` +
        `When omitted, all accessible mailboxes (own + delegated) are searched. ` +
        `Use the \`list_mailboxes_and_directories\` tool to discover which mailboxes are available for the current user.`,
    )
    .optional(),
  kqlQuery: z
    .string()
    .nonempty()
    .describe(
      'KQL (Keyword Query Language) query string for Microsoft Graph email search.\n' +
        'Supported property filters:\n' +
        '  from:<email>                    — sender (SMTP address, display name, or domain)\n' +
        '  to:<email>                      — To recipient (SMTP address, display name, or domain)\n' +
        '  cc:<email>                      — CC recipient\n' +
        '  bcc:<email>                     — BCC recipient\n' +
        '  participants:<email>            — any of from/to/cc/bcc (broad people search across all address fields)\n' +
        '  recipients:<email>              — any of to/cc/bcc\n' +
        '  subject:<words>                 — words in subject line (phrase: subject:"budget report")\n' +
        '  body:<words>                    — words in message body\n' +
        '  attachment:<filename>           — attached file name (wildcards OK: attachment:report*)\n' +
        '  received>=YYYY-MM-DD            — received on or after date\n' +
        '  received<=YYYY-MM-DD            — received on or before date\n' +
        '  sent>=YYYY-MM-DD                — sent on or after date\n' +
        '  sent<=YYYY-MM-DD                — sent on or before date\n' +
        '  hasAttachment:true/false        — whether the email has attachments\n' +
        '  category:"label"                — Outlook category label\n' +
        '  importance:low/medium/high      — email importance level\n' +
        '  kind:email/meetings/voicemail   — message type; other values: contacts, docs, faxes, im, journals, notes, posts, rssfeeds, tasks\n' +
        '  size>=<bytes>                   — message size in bytes (e.g. size>=1048576 for >1 MB); range: size:1..1048576\n' +
        'Syntax rules:\n' +
        '  - NO space between property name and value: from:alice@example.com NOT from: alice@example.com\n' +
        '  - Boolean operators AND/OR/NOT must be UPPERCASE\n' +
        '  - Suffix wildcards only: report* or budget*, NOT *report\n' +
        '  - Phrases must be in double quotes: subject:"quarterly report"\n' +
        '  - DO NOT use folder: — it is not supported and will cause a request error\n' +
        'Free-text terms (no property prefix) search across subject, body, and from.\n' +
        'Examples:\n' +
        '  "from:alice@example.com subject:\\"Q2 budget\\" received>=2024-01-01"\n' +
        '  "project proposal hasAttachment:true received>=2024-03-01 received<=2024-03-31"\n' +
        '  "from:hr@acme.com OR from:payroll@acme.com subject:salary"\n' +
        '  "participants:alice@example.com kind:meetings received>=2024-01-01"',
    ),
  limit: z
    .number()
    .int()
    .min(SEARCH_CONFIG.msGraph.subQueryLimits.min)
    .max(SEARCH_CONFIG.msGraph.subQueryLimits.max)
    .optional()
    .prefault(SEARCH_CONFIG.msGraph.subQueryLimits.default)
    .describe(SEARCH_CONFIG.msGraph.subQueryLimits.description),
});

export const MsGraphSearchParamsSchema = z
  .array(MsGraphKqlQuerySchema)
  .min(1)
  .max(10)
  .describe('List of KQL queries to execute in parallel. Maximum 10.');

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
          'A single phrasing often misses relevant emails — always compose 2–4 parallel entries that approach the question from different angles: ' +
          '(1) different phrasings or synonyms (e.g. "project kick-off" vs "project launch"); ' +
          '(2) narrower vs. broader scope — one with tight conditions, one with a broader search term; ' +
          '(3) different condition combinations (e.g. one entry scoped to folder "Inbox", another to "Sent Items" to capture both sides of a conversation); ' +
          '(4) perspective shift (e.g. "emails I sent about the merger" vs "emails I received about the merger"). ' +
          'Reason about the user\'s question first: when they clearly name a specific sender, recipient, date range, folder, attachment requirement, or category, prefer expressing it via `conditions` on every entry that targets the same intent rather than encoding it only in the natural-language `search` text. If a signal is ambiguous, it is fine to omit the condition — but generally lean toward populating them when the intent is clear. Example: user asks "emails from alice@x.com about the budget" → every entry should include `conditions: [{ fromSenders: { value: "alice@x.com", operator: "equals" } }]`, with `search` carrying only the topic ("budget"). ' +
          'IMPORTANT: uniqueSemanticSearchQueries supports delegated-access mailboxes — use the mailbox field to scope searches to specific mailboxes including delegated ones. ' +
          'Results from all searches are merged and deduplicated by email ID.',
      ),
    msGraphKeywordSearchQueries: MsGraphSearchParamsSchema.describe(
      'KQL queries that address the SAME single user question as uniqueSemanticSearchQueries, expressed using keyword/lexical search. ' +
        'Use multiple entries to approach the same question from different angles (e.g. different keyword combinations, subject vs. body focus). ' +
        'Results from both backends are merged: semantic results are anchored first and enriched with the Graph body excerpt when the same email was matched by both. ' +
        'A single backend alone will miss results: semantic may miss exact keyword hits; KQL will miss conceptual matches and attachment content.',
    ),
  })
  .describe(
    'IMPORTANT: ALWAYS populate both uniqueSemanticSearchQueries and msGraphKeywordSearchQueries. ' +
      'Both fields must address the SAME single user question, each using its own query language and approaching the question from different angles. ' +
      'Do NOT spread multiple unrelated user questions across the two fields. ' +
      'The two searches run in parallel and their results are merged to provide a broader and more reliable overview: ' +
      'semantic search covers natural-language relevance and attachment content; ' +
      'KQL covers lexical precision and full email-body excerpts.',
  );
