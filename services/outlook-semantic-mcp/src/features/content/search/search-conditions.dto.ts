import { MetadataFilter, UniqueQLOperator } from '@unique-ag/unique-api';
import { first } from 'remeda';
import { z } from 'zod';

const ConditionFieldSchema = <T extends z.ZodTypeAny>(valueSchema: T) =>
  z.object({
    value: valueSchema,
    operator: z.enum(UniqueQLOperator),
  });

const EXAMPLE_FOLDER_IDS = {
  first:
    'AQMkADllMDJjNDk0LWNiNmEtNDhlOC04YjA4LWMzNDZlOTkANzlhMmMALgAAA8XAUl8fmjpEkM39lOfyshYBAMjQHeJoK_1Bt2gTZjb69YQAAAIBCAAAAA==',
  second:
    'AQMkADllMDJjNDk0LWNiNmEtNDhlOC04YjA4LWMzNDZlOTkANzlhMmMALgAAA8XAUl8fmjpEkM39lOfyshYBAMjQHeJoK_1Bt2gTZjb69YQAAAIBWQAAAA==',
  third:
    'AQMkADllMDJjNDk0LWNiNmEtNDhlOC04YjA4LWMzNDZlOTkANzlhMmMALgAAA8XAUl8fmjpEkM39lOfyshYBAMjQHeJoK_1Bt2gTZjb69YQAAAIBCgAAAA==',
};

export const SearchConditionSchema = z
  .object({
    dateFrom: ConditionFieldSchema(
      z.iso
        .datetime()
        .describe(
          'Filter emails received on or after this date. ISO 8601 format, e.g. "2024-01-01T00:00:00Z". Recommended operators: greaterThanOrEqual, greaterThan.',
        ),
    ).optional(),
    dateTo: ConditionFieldSchema(
      z.iso
        .datetime()
        .describe(
          'Filter emails received on or before this date. ISO 8601 format, e.g. "2024-12-31T23:59:59Z". Recommended operators: lessThanOrEqual, lessThan.',
        ),
    ).optional(),
    fromSenders: ConditionFieldSchema(
      z
        .array(z.email())
        .or(z.email())
        .describe(
          'Sender email address(es) to filter by, e.g. "alice@example.com" or ["alice@example.com", "bob@example.com"]. Recommended operators: equals, in.',
        ),
    ).optional(),
    toRecipients: ConditionFieldSchema(
      z
        .array(z.email())
        .or(z.email())
        .describe(
          'Recipient email address(es) to filter by, e.g. "carol@example.com" or ["carol@example.com"]. Recommended operators: equals for string parameter, in for array or contains.',
        ),
    ).optional(),
    ccRecipients: ConditionFieldSchema(
      z
        .array(z.email())
        .or(z.email())
        .describe(
          'CC email address(es) to filter by, e.g. "carol@example.com" or ["carol@example.com"]. Recommended operators: equals for string parameter, in for array or contains.',
        ),
    ).optional(),
    directories: ConditionFieldSchema(
      z
        .array(z.string())
        .or(z.string())
        .describe(
          `Folder ID(s) to filter by, e.g. "${EXAMPLE_FOLDER_IDS.first}" or ["${EXAMPLE_FOLDER_IDS.second}", "${EXAMPLE_FOLDER_IDS.third}"]. Folder ids can be found using \`list_folders\` tool. Recommended operators: equals for string parameter, in for array or contains.`,
        ),
    ).optional(),
    hasAttachments: ConditionFieldSchema(
      z
        .boolean()
        .describe(
          'Whether the email has attachments, e.g. true or false. Recommended operator: equals.',
        ),
    ).optional(),
    categories: ConditionFieldSchema(
      z
        .array(z.string())
        .or(z.string())
        .describe(
          `Category label(s) to filter by, e.g. "Important" or ["Important", "Project-X"]. Categories can be found using \`list_categories\` tool. Recommended operators: equals for string parameter, in for array or contains.`,
        ),
    ).optional(),
  })
  .refine((obj) => Object.values(obj).some((v) => v !== undefined), {
    message:
      'At least one condition field must be provided. Example: { fromSenders: { value: "alice@example.com", operator: "Equal" } }',
  })
  .describe(
    `Condition to narrow down the search, AND operator is applied between mutiple conditions fields`,
  );

export type SearchCondition = z.infer<typeof SearchConditionSchema>;

export const SearchEmailsInputSchema = z.object({
  search: z.string().nonempty().describe(`Search query`),
  conditions: z
    .array(SearchConditionSchema)
    .optional()
    .describe(
      `Conditions to narrow down the search, If we pass multiple conditions we apply OR operator between them.`,
    ),
  limit: z
    .number()
    .int()
    .min(40)
    .max(100)
    .optional()
    .prefault(40)
    .describe('Maximum number of results to return. Must be between 40 and 100.'),
  scoreThreshold: z
    .number()
    .min(0)
    .max(1)
    .optional()
    .describe('Minimum relevance score threshold for returned results, between 0 and 1.'),
});

export type SearchEmailsInput = z.infer<typeof SearchEmailsInputSchema>;

const METADATA_PATH: Record<keyof SearchCondition, string[]> = {
  dateFrom: ['receivedDateTime'],
  dateTo: ['receivedDateTime'],
  fromSenders: ['from.emailAddress'],
  toRecipients: ['toRecipients.emailAddresses'],
  ccRecipients: ['ccRecipients.emailAddresses'],
  directories: ['parentFolderId'],
  hasAttachments: ['hasAttachments'],
  categories: ['categories'],
};

function wrapConditions(filters: MetadataFilter[], operator: 'and' | 'or'): MetadataFilter {
  const firstElement = first(filters);
  if (firstElement && filters.length === 1) {
    return firstElement;
  }
  if (operator === 'and') {
    return { and: filters };
  }
  return { or: filters };
}

function getConditionsArray(conditions: SearchCondition): MetadataFilter[] {
  const leaves: MetadataFilter[] = [];

  for (const key of Object.keys(conditions) as Array<keyof SearchCondition>) {
    const field = conditions[key];
    if (field === undefined) {
      continue;
    }

    const path = METADATA_PATH[key];
    const { operator } = field;
    const { value } = field;
    leaves.push({ path, operator, value });
  }

  return leaves;
}

function buildConditionGroup(condition: SearchCondition): MetadataFilter {
  const leaves: MetadataFilter[] = [];
  leaves.push(...getConditionsArray(condition));
  return wrapConditions(leaves, 'and');
}

// Keys within a single condition are OR-combined; multiple conditions in the array are AND-combined.
export function buildSearchFilter(
  conditions: SearchCondition[] | null | undefined,
): MetadataFilter | undefined {
  if (!conditions?.length) {
    return undefined;
  }
  const conditionGroups = conditions.map(buildConditionGroup);
  return wrapConditions(conditionGroups, 'or');
}
