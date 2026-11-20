import { isArray, isNumber, isPlainObject, isString } from 'remeda';
import * as z from 'zod';

const TitledRecordSchema = z.object({
  title: z.string().describe('Human-readable label of the record, for citing it'),
  record: z.unknown().describe('The record exactly as Temenos returned it'),
});

type TitledRecord = z.infer<typeof TitledRecordSchema>;

export const TemenosRecordsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z
      .array(TitledRecordSchema)
      .optional()
      .describe('One entry per Temenos record, each with a title and the record itself'),
    header: z.unknown().optional().describe('Temenos response header (paging, status)'),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type TemenosRecordsResult = z.infer<typeof TemenosRecordsOutputSchema>;

const NAME_KEY = /(?:name|description|subject)$/i;
const ID_KEY = /Id$/;

/**
 * Temenos answers with a `{ header, body }` envelope whose records carry no web link and no
 * generic title field. Each record is wrapped as `{ title, record }` under `data`, so a chat
 * client can cite every record by a readable title instead of the result as a whole.
 */
export function toTitledRecords(
  response: unknown,
  label: string,
): Pick<TemenosRecordsResult, 'data' | 'header'> {
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

function recordId(record: Record<string, unknown>): string | undefined {
  const key =
    ['id', 'recordId'].find((k) => k in record) ?? Object.keys(record).find((k) => ID_KEY.test(k));
  const value = key === undefined ? undefined : record[key];
  if (isString(value) && value.trim()) {
    return value.trim();
  }
  return isNumber(value) ? String(value) : undefined;
}

// Temenos keeps multi-valued fields as arrays of objects, e.g. `descriptions: [{ description }]`.
function recordName(record: Record<string, unknown>): string | undefined {
  for (const [key, value] of Object.entries(record)) {
    if (NAME_KEY.test(key) && isString(value) && value.trim()) {
      return value.trim();
    }
  }
  for (const value of Object.values(record)) {
    const [first] = isArray(value) ? value : [];
    if (isPlainObject(first)) {
      const name = recordName(first);
      if (name !== undefined) {
        return name;
      }
    }
  }
  return undefined;
}
