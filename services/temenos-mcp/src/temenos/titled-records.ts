import { isArray, isNumber, isPlainObject, isString } from 'remeda';
import * as z from 'zod';

const TitledRecordSchema = z.object({
  title: z.string().describe('Human-readable label of the record, for citing it'),
  record: z.unknown().describe('The record exactly as Temenos returned it'),
});

type TitledRecord = z.infer<typeof TitledRecordSchema>;

export const TitledRecordsSchema = z
  .array(TitledRecordSchema)
  .describe('One entry per Temenos record, each with a title and the record itself');

export const TemenosHeaderSchema = z.unknown().describe('Temenos response header (paging, status)');

const NAME_KEY = /(?:name|description|subject)$/i;
const ID_KEY = /Id$/;

/** Wraps each record as `{ title, record }` under `data`; the Temenos header stays in `header`. */
export function toTitledRecords(
  response: unknown,
  label: string,
): { data: TitledRecord[]; header?: unknown } {
  if (isPlainObject(response) && 'body' in response) {
    return { data: recordsOf(response.body).map((r) => titled(r, label)), header: response.header };
  }
  return { data: recordsOf(response).map((r) => titled(r, label)) };
}

function recordsOf(value: unknown): readonly unknown[] {
  if (isArray(value)) {
    return value;
  }
  return value === undefined || value === null ? [] : [value];
}

function titled(record: unknown, label: string): TitledRecord {
  if (!isPlainObject(record)) {
    return { title: label, record };
  }
  const id = recordId(record);
  const head = id === undefined ? label : `${label} ${id}`;
  const name = recordName(record);
  return { title: name === undefined ? head : `${head} - ${name}`, record };
}

// The first usable value wins, in order: `id`, `recordId`, then any other `...Id` field.
function recordId(record: Record<string, unknown>): string | undefined {
  for (const key of ['id', 'recordId', ...Object.keys(record).filter((k) => ID_KEY.test(k))]) {
    const value = record[key];
    if (isString(value) && value.trim()) {
      return value.trim();
    }
    if (isNumber(value)) {
      return String(value);
    }
  }
  return undefined;
}

// Temenos keeps multi-valued fields as arrays of objects, e.g. `descriptions: [{ description }]`.
function recordName(record: Record<string, unknown>): string | undefined {
  for (const [key, value] of Object.entries(record)) {
    if (NAME_KEY.test(key) && isString(value) && value.trim()) {
      return value.trim();
    }
  }
  for (const value of Object.values(record)) {
    for (const entry of isArray(value) ? value : []) {
      const name = isPlainObject(entry) ? recordName(entry) : undefined;
      if (name !== undefined) {
        return name;
      }
    }
  }
  return undefined;
}
