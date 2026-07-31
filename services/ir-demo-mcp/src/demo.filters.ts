import assert from 'node:assert/strict';
import type { DemoRecord } from './data/demo-record';

const normalized = (value: string): string => value.trim().toLocaleLowerCase();
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item: unknown) => typeof item === 'string');

const searchableValue = (value: unknown): string => {
  if (Array.isArray(value)) {
    return value.map(searchableValue).join(' ');
  }
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
};

export const matchesValue = (
  record: DemoRecord,
  field: string,
  expected: string | undefined,
): boolean => {
  if (expected === undefined) {
    return true;
  }
  const value = record.data[field];
  return typeof value === 'string' && normalized(value) === normalized(expected);
};

export const matchesListValue = (
  record: DemoRecord,
  fields: readonly string[],
  expected: string | undefined,
): boolean => {
  if (expected === undefined) {
    return true;
  }
  const expectedValue = normalized(expected);
  return fields.some((field) => {
    const value = record.data[field];
    return Array.isArray(value)
      ? value.some((item) => typeof item === 'string' && normalized(item) === expectedValue)
      : typeof value === 'string' && normalized(value) === expectedValue;
  });
};

export const matchesQuery = (
  record: DemoRecord,
  fields: readonly string[],
  query: string | undefined,
): boolean => {
  if (query === undefined) {
    return true;
  }
  const needle = normalized(query);
  return fields.some((field) => normalized(searchableValue(record.data[field])).includes(needle));
};

export const matchesDateRange = (
  record: DemoRecord,
  field: string,
  dateFrom: string | undefined,
  dateTo: string | undefined,
): boolean => {
  if (dateFrom === undefined && dateTo === undefined) {
    return true;
  }
  const value = record.data[field];
  if (typeof value !== 'string') {
    return false;
  }
  const date = value.slice(0, 10);
  return (dateFrom === undefined || date >= dateFrom) && (dateTo === undefined || date <= dateTo);
};

export const compareByDate = (
  left: DemoRecord,
  right: DemoRecord,
  field: string,
  direction: 'ascending' | 'descending',
): number => {
  const leftValue = dateTimestamp(left.data[field]);
  const rightValue = dateTimestamp(right.data[field]);
  if (leftValue === undefined) {
    return rightValue === undefined ? 0 : 1;
  }
  if (rightValue === undefined) {
    return -1;
  }
  return direction === 'ascending' ? leftValue - rightValue : rightValue - leftValue;
};

export const toPublicRecord = (record: DemoRecord): Record<string, unknown> => ({
  ...record.data,
  id: record.id,
  relationshipId: record.relationshipId,
});

export const toPublicRelationship = (record: DemoRecord): Record<string, unknown> => {
  const kind = record.data.kind;
  const name = record.data.name ?? record.data.lpName ?? record.data.institution;
  assert.ok(
    kind === 'existing' || kind === 'prospect',
    `Relationship "${record.id}" has invalid kind`,
  );
  assert.ok(typeof name === 'string', `Relationship "${record.id}" has no name`);
  return {
    ...toPublicRecord(record),
    kind,
    name,
    relationshipType: kind === 'existing' ? 'investor' : 'prospect',
  };
};

export const normalizeDiligenceRecord = (record: DemoRecord): DemoRecord => {
  const sourceType = record.data.ddqType;
  const sourceStatus = record.data.status ?? record.data.ddqStatus;
  const sourceTargetDate = record.data.dueDate ?? record.data.targetCompletionDate ?? null;
  assert.ok(
    sourceType === undefined || typeof sourceType === 'string',
    `Diligence record "${record.id}" has invalid type`,
  );
  assert.ok(typeof sourceStatus === 'string', `Diligence record "${record.id}" has invalid status`);
  assert.ok(
    sourceTargetDate === null || typeof sourceTargetDate === 'string',
    `Diligence record "${record.id}" has invalid target date`,
  );
  return {
    ...record,
    data: {
      ...record.data,
      type: sourceType ?? 'Prospect DDQ',
      status: sourceStatus,
      targetDate: sourceTargetDate,
    },
  };
};

export const toPublicMessage = (record: DemoRecord): Record<string, unknown> => {
  const sender = record.data.from;
  const to = record.data.to;
  const cc = record.data.cc ?? [];
  assert.ok(typeof sender === 'string', `Message "${record.id}" has no sender`);
  assert.ok(isStringArray(to), `Message "${record.id}" has invalid To recipients`);
  assert.ok(isStringArray(cc), `Message "${record.id}" has invalid Cc recipients`);
  return {
    ...toPublicRecord(record),
    sender,
    recipients: [...to, ...cc],
  };
};

const dateTimestamp = (value: unknown): number | undefined => {
  if (typeof value !== 'string') {
    return undefined;
  }
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? undefined : timestamp;
};
