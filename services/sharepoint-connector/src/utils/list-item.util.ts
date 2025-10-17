import { ListItem } from '../msgraph/types/sharepoint.types';

export function getTitle(fields: ListItem['fields']): string {
  const title = fields.Title?.trim();

  if (!title || title.toLowerCase() === 'title') {
    return fields.FileLeafRef;
  }

  return title;
}
