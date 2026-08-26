import { describe, expect, it } from 'vitest';
import { buildEventGraphFilter } from '../event-graph-filter';

describe('buildEventGraphFilter', () => {
  it('returns undefined when nothing can be pushed to Graph', () => {
    expect(buildEventGraphFilter({})).toBeUndefined();
  });

  it('builds a single-category clause', () => {
    expect(buildEventGraphFilter({ categories: ['Client'] })).toBe(
      "categories/any(c:c eq 'Client')",
    );
  });

  it('pushes down only the first category because calendarView accepts one comparison', () => {
    // Safe narrowing rather than a partial answer: events carrying both categories are a subset of
    // those carrying the first, and matchesFilters still requires both.
    expect(buildEventGraphFilter({ categories: ['Client', 'Urgent'] })).toBe(
      "categories/any(c:c eq 'Client')",
    );
  });

  it('builds a startswith clause for a subject prefix', () => {
    expect(buildEventGraphFilter({ subject: { startsWith: 'Weekly' } })).toBe(
      "startswith(subject,'Weekly')",
    );
  });

  it('leaves a subject substring to in-process matching', () => {
    expect(buildEventGraphFilter({ subject: { contains: 'Weekly' } })).toBeUndefined();
  });

  it('ands a category and a subject prefix', () => {
    expect(
      buildEventGraphFilter({ categories: ['Client'], subject: { startsWith: 'Weekly' } }),
    ).toBe("categories/any(c:c eq 'Client') and startswith(subject,'Weekly')");
  });

  it('doubles single quotes so a value cannot terminate the literal', () => {
    expect(buildEventGraphFilter({ categories: ["O'Brien"] })).toBe(
      "categories/any(c:c eq 'O''Brien')",
    );
    expect(buildEventGraphFilter({ subject: { startsWith: "') or true or ('" } })).toBe(
      "startswith(subject,''') or true or (''')",
    );
  });

  it('ignores blank and empty categories', () => {
    expect(buildEventGraphFilter({ categories: ['   '] })).toBeUndefined();
    expect(buildEventGraphFilter({ categories: [] })).toBeUndefined();
  });
});
