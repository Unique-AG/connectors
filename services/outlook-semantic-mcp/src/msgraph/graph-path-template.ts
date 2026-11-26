// Graph path words are lowerCamelCase, maybe dotted or `$`-prefixed (`microsoft.graph.delta`).
// Any other segment (mailbox address, GUID, item id) identifies a user or an item: `:id`.
const apiWord = /^\$?[a-z][a-zA-Z]*(\.[a-zA-Z]+)*$/;

const isIdentifierSegment = (segment: string): boolean => segment !== '' && !apiWord.test(segment);

/** `…/v1.0/users/jane@contoso.com/messages/AAMk…` → `/users/:id/messages/:id` */
export const toGraphPathTemplate = (request: RequestInfo): string => {
  try {
    const url = typeof request === 'string' ? request : request.url;
    const path = new URL(url).pathname.replace(/^\/v\d+(\.\d+)?/, '') || '/';
    return path
      .split('/')
      .map((segment) => (isIdentifierSegment(segment) ? ':id' : segment))
      .join('/');
  } catch {
    return 'unknown';
  }
};
