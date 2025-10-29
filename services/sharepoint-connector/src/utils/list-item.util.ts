import { ListItem } from '../msgraph/types/sharepoint.types';

export function getTitle(fields: ListItem['fields']): string {
  const title = fields.Title?.trim();
  // The title sometimes comes back as default value Title, even though the file leaf ref has a valid name. Because of this we fallback to the file leaf ref instead of displaying the default value.
  // FileLeafRef is the file name
  if (fields.FileLeafRef && (!title || title.toLowerCase() === 'title')) {
    return fields.FileLeafRef;
  }

  return title;
}
