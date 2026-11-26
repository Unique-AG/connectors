import { describe, expect, it } from 'vitest';
import { NO_SUBJECT, subjectOrFallback } from '../no-subject';

describe('subjectOrFallback', () => {
  it('returns the subject trimmed', () => {
    expect(subjectOrFallback('  Budget Q3 ')).toBe('Budget Q3');
  });

  it.each([null, undefined, '', '   '])('returns "(no subject)" for %j', (subject) => {
    expect(subjectOrFallback(subject)).toBe(NO_SUBJECT);
  });

  it('returns the first subject that is not blank', () => {
    expect(subjectOrFallback('  ', null, 'Budget Q3', 'Other')).toBe('Budget Q3');
  });
});
