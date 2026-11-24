import { z } from 'zod';

const uuidSchema = z.uuid();

// Mailbox addresses and Graph ids in a path identify a user or an item, so they become `:id`.
const isIdentifierSegment = (segment: string): boolean =>
  segment.includes('@') ||
  segment.includes('%40') ||
  uuidSchema.safeParse(segment).success ||
  (segment.length > 15 && /\d/.test(segment));

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
