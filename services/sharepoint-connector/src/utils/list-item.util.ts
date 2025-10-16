import {ListItem} from "../msgraph/types/sharepoint.types";

export function getTitle(fields: ListItem['fields'] ): string {
  if(fields.Title === 'Title') return fields.FileLeafRef
  return fields.Title
}