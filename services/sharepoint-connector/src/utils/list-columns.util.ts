import type { List } from '@microsoft/microsoft-graph-types';
import { filter, isNonNullish, map, pipe } from 'remeda';
import type { ListColumn } from '../microsoft-apis/graph/types/sharepoint.types';

type ColumnNames = Pick<ListColumn, 'name' | 'displayName'>;

export function columnsOf(list: List): ColumnNames[] {
  return pipe(
    list.columns ?? [],
    filter((column): column is typeof column & { name: string } => isNonNullish(column.name)),
    map((column) => ({ name: column.name, displayName: column.displayName ?? column.name })),
  );
}

// Accepts the display name shown in the SharePoint UI or the internal name, and returns the
// internal name the API uses.
export function resolveColumnName(columns: ColumnNames[], columnName: string): string | undefined {
  const byDisplayName = columns.find((column) => column.displayName === columnName);
  if (byDisplayName) {
    return byDisplayName.name;
  }
  return columns.find((column) => column.name === columnName)?.name;
}
