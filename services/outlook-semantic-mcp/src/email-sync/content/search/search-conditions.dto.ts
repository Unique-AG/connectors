import { MetadataFilter, UniqueQLOperator } from '@unique-ag/unique-api';
import { first, omit, pick } from 'remeda';
import { z } from 'zod';

const ConditionFieldSchema = <T extends z.ZodTypeAny>(valueSchema: T) =>
  z.object({
    value: valueSchema.describe('The value to filter by.'),
    operator: z.nativeEnum(UniqueQLOperator).describe('The comparison operator to apply.'),
  });

export const SearchConditionSchema = z
  .object({
    dateFrom: ConditionFieldSchema(z.iso.datetime())
      .optional()
      .describe('Filter emails received on or after this date (ISO 8601 format).'),
    dateTo: ConditionFieldSchema(z.iso.datetime())
      .optional()
      .describe('Filter emails received on or before this date (ISO 8601 format).'),
    fromSenders: ConditionFieldSchema(z.array(z.string()))
      .optional()
      .describe('Filter emails sent by any of the given sender email addresses.'),
    toRecipients: ConditionFieldSchema(z.array(z.string()))
      .optional()
      .describe('Filter emails addressed to any of the given recipient email addresses.'),
    ccRecipients: ConditionFieldSchema(z.array(z.string()))
      .optional()
      .describe('Filter emails CC-ed to any of the given email addresses.'),
    directories: ConditionFieldSchema(z.array(z.string()))
      .optional()
      .describe('Filter emails located in any of the given folder IDs.'),
    hasAttachments: ConditionFieldSchema(z.boolean())
      .optional()
      .describe('Filter emails by whether they have attachments.'),
    categories: ConditionFieldSchema(z.array(z.string()))
      .optional()
      .describe('Filter emails tagged with any of the given categories.'),
  })
  .refine((obj) => Object.values(obj).some((v) => v !== undefined), {
    message: 'At least one condition field must be provided',
  });

export type SearchCondition = z.infer<typeof SearchConditionSchema>;

export const SearchEmailsInputSchema = z.object({
  search: z.string().describe(`Search query`),
  conditions: z
    .array(SearchConditionSchema)
    .optional()
    .describe(
      `Conditions to narrow down the search, If we pass multiple conditions we apply AND operator between them.`,
    ),
  limit: z
    .number()
    .int()
    .min(1)
    .max(100)
    .default(10)
    .describe('Maximum number of results to return. Must be between 1 and 100.'),
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

    if (Array.isArray(value)) {
      const arrayLeaves = value.map(
        (subValue: string): MetadataFilter => ({
          path,
          operator,
          value: subValue,
        }),
      );
      leaves.push(wrapConditions(arrayLeaves, 'or'));
    } else {
      leaves.push({ path, operator, value: typeof value === 'boolean' ? String(value) : value });
    }
  }

  return leaves;
}

function buildConditionGroup(condition: SearchCondition): MetadataFilter {
  const leaves: MetadataFilter[] = [];

  const dateIntervalFields = ['dateFrom', 'dateTo'] as const;

  const dateLeavesConditions = getConditionsArray(pick(condition, dateIntervalFields));
  if (dateLeavesConditions.length) {
    leaves.push(wrapConditions(dateLeavesConditions, 'and'));
  }

  const otherConditions = getConditionsArray(omit(condition, dateIntervalFields));
  leaves.push(...otherConditions);

  return wrapConditions(leaves, 'or');
}

// Keys within a single condition are OR-combined; multiple conditions in the array are AND-combined.
export function buildSearchFilter(
  conditions: SearchCondition[] | null | undefined,
): MetadataFilter | undefined {
  if (!conditions?.length) {
    return undefined;
  }
  const conditionGroups = conditions.map(buildConditionGroup);
  return wrapConditions(conditionGroups, 'and');
}
