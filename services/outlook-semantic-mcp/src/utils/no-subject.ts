import type { Nullish } from './nullish';

// What Outlook shows for a message or event without a subject.
export const NO_SUBJECT = '(no subject)';

export function subjectOrFallback(...subjects: Nullish<string>[]): string {
  return subjects.map((subject) => subject?.trim()).find(Boolean) ?? NO_SUBJECT;
}
