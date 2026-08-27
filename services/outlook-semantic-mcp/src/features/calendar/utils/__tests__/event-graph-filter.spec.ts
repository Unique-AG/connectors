import { describe, expect, it } from 'vitest';
import { buildEventGraphFilter } from '../event-graph-filter';

describe('buildEventGraphFilter', () => {
  it('returns undefined when nothing can be pushed to Graph', () => {
    expect(buildEventGraphFilter({})).toBeUndefined();
  });

  it('builds a startswith clause for a subject prefix', () => {
    expect(buildEventGraphFilter({ subject: { startsWith: 'Weekly' } })).toBe(
      "subject ne null and startswith(subject,'Weekly')",
    );
  });

  it('builds a contains clause for a subject substring', () => {
    expect(buildEventGraphFilter({ subject: { contains: 'Weekly' } })).toBe(
      "subject ne null and contains(subject,'Weekly')",
    );
  });

  it('guards every subject clause against a null subject', () => {
    // Graph answers 500, not an empty match, when any event in the window has no subject.
    expect(buildEventGraphFilter({ subject: { startsWith: 'Weekly' } })).toContain(
      'subject ne null and ',
    );
    expect(buildEventGraphFilter({ subject: { contains: 'Weekly' } })).toContain(
      'subject ne null and ',
    );
  });

  it('doubles single quotes so a value cannot terminate the literal', () => {
    expect(buildEventGraphFilter({ subject: { startsWith: "') or true or ('" } })).toBe(
      "subject ne null and startswith(subject,''') or true or (''')",
    );
    expect(buildEventGraphFilter({ subject: { contains: "') or true or ('" } })).toBe(
      "subject ne null and contains(subject,''') or true or (''')",
    );
  });
});
