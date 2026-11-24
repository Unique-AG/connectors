// Graph's own path words are lowerCamelCase, some dotted (`microsoft.graph.delta`) or `$`-prefixed
// (`$value`). Every other segment, such as a mailbox address, a GUID or an item id with or without
// digits, identifies a user or an item, so it becomes `:id`.
const apiWord = /^\$?[a-z][a-zA-Z]*(\.[a-zA-Z]+)*$/;

const isIdentifierSegment = (segment: string): boolean => segment !== '' && !apiWord.test(segment);

/** `https://graph.microsoft.com/v1.0/users/jane@contoso.com/messages/AAMk…` → `/users/:id/messages/:id` */
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
