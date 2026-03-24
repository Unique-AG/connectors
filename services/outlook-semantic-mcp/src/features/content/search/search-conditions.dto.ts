import { MetadataFilter, UniqueQLOperator } from '@unique-ag/unique-api';
import { first } from 'remeda';
import { z } from 'zod';
import { MessageMetadata } from '~/features/mail-ingestion/utils/get-metadata-from-message';
import { clampToValidDate } from '~/utils/clamp-to-valid-date';

export const CONTAINS_ANY_OPERATOR = 'containsAny' as const;

const ArrayConditionFieldSchema = <T extends z.ZodArray>(
  itemSchema: T,
  { isStrict = false } = {},
) =>
  z.object({
    value: itemSchema,
    operator: isStrict
      ? z.enum([UniqueQLOperator.IN, UniqueQLOperator.NOT_IN])
      : z.enum([UniqueQLOperator.IN, UniqueQLOperator.NOT_IN, CONTAINS_ANY_OPERATOR]),
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

const emailConditionsSchema = (label: string) =>
  SingularConditionFieldSchema(
    z
      .string()
      .describe(
        `${label} email address to filter by, e.g. "alice@example.com". Must be look like an email address. Recommended operators: equals, contains`,
      ),
  )
    .or(
      ArrayConditionFieldSchema(z.array(z.string())).describe(
        `${label} email addresses to filter by, e.g. ["alice@example.com", "bob@example.com"]. Must be look like an email address. Prefer containsAny when matching a list of emails (expands to partial contains checks). Use in/notIn only for exact equality matching.`,
      ),
    )
    .optional();

const clampedDatetime = z.preprocess(clampToValidDate, z.iso.datetime());

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
    directories: ArrayConditionFieldSchema(
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
      { isStrict: true },
    ).optional(),
    hasAttachments: SingularConditionFieldSchema(
      z
        .boolean()
        .describe(
          'Whether the email has attachments, e.g. true or false. Recommended operator: equals, notEquals.',
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
    message:
      'At least one condition field must be provided. Example: { fromSenders: { value: "alice@example.com", operator: "equals" } }',
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
});

export type SearchEmailsInput = z.infer<typeof SearchEmailsInputSchema>;

const METADATA_PATH: Record<keyof SearchCondition, (keyof MessageMetadata)[]> = {
  dateFrom: ['receivedDateTime'],
  dateTo: ['receivedDateTime'],
  fromSenders: ['fromEmailAddress'],
  toRecipients: ['toRecipientsEmailAddresses'],
  ccRecipients: ['ccRecipientsEmailAddresses'],
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
    const operator = field.operator as UniqueQLOperator | typeof CONTAINS_ANY_OPERATOR;
    const { value } = field;
    if (operator === CONTAINS_ANY_OPERATOR) {
      // We do not assert because it's not worth breaking the response to the agent.
      if (Array.isArray(value)) {
        leaves.push(
          wrapConditions(
            value.map((v) => ({ path, operator: UniqueQLOperator.CONTAINS, value: v })),
            'or',
          ),
        );
      }
    } else {
      leaves.push({ path, operator, value });
    }
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
