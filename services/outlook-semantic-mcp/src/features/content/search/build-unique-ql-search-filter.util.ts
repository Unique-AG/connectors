import assert from 'node:assert';
import { MetadataFilter, UniqueQLOperator } from '@unique-ag/unique-api';
import { first } from 'remeda';
import { MessageMetadata } from '~/features/process-email/utils/get-metadata-from-message';
import { CONTAINS_ANY_OPERATOR, SearchCondition } from './semantic-search-conditions.dto';

const METADATA_PATH: Record<
  Exclude<keyof SearchCondition, 'mailbox'>,
  (keyof MessageMetadata)[]
> = {
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
    if (field === undefined || typeof field === 'string') {
      continue;
    }

    const path = METADATA_PATH[key as Exclude<keyof SearchCondition, 'mailbox'>];
    if (!path) {
      continue;
    }
    const operator = field.operator as UniqueQLOperator | typeof CONTAINS_ANY_OPERATOR;
    const { value } = field;
    if (operator === CONTAINS_ANY_OPERATOR) {
      // We use assert here as type guard because zod already validates this but typescript does not infer that we can
      // have just array as value.
      assert.ok(
        Array.isArray(value),
        `Invalid value for operator: ${CONTAINS_ANY_OPERATOR}. Value: ${value} must be an array`,
      );
      const conditions = value.map((value) => ({
        path,
        operator: UniqueQLOperator.CONTAINS,
        value,
      }));
      // We do not break if conditions length is empty we skip it beause there is no point
      // in applying this condition.
      if (conditions.length > 0) {
        leaves.push(wrapConditions(conditions, 'or'));
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

// Fields within a single condition are AND-combined; multiple conditions in the array are OR-combined.
export function buildSearchFilter(
  conditions: SearchCondition[] | null | undefined,
): MetadataFilter | undefined {
  if (!conditions?.length) {
    return undefined;
  }
  const conditionGroups = conditions.map(buildConditionGroup);
  return wrapConditions(conditionGroups, 'or');
}
