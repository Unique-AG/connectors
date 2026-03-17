import { SQL, SQLChunk, StringChunk, sql } from 'drizzle-orm';

// Drizzle does not support sending array parameters directly — passing a JS array
// as a query parameter serializes it incorrectly. This function builds the ARRAY[...]
// literal manually so each element is bound as a separate parameterized value.
export function sqlArray(arr: string[]): SQL {
  const chunks: SQLChunk[] = [new StringChunk('ARRAY[')];
  arr.forEach((item, index) => {
    if (index > 0) {
      chunks.push(new StringChunk(', '));
    }
    chunks.push(sql`${item}`);
  });
  chunks.push(new StringChunk(']'));
  return new SQL(chunks);
}
