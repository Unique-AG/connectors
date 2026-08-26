export type SubjectFilter = { startsWith: string } | { contains: string };

/**
 * OData escapes a single quote inside a string literal by doubling it. Subject and category text
 * arrives from tool input, so this is the same boundary concern as SmtpAddressSchema: without it a
 * subject containing an apostrophe either breaks the query or changes what it asks for.
 */
function escapeODataString(value: string): string {
  return value.replaceAll("'", "''");
}

/**
 * The server-side half of the event filters. calendarView accepts one category comparison and
 * startswith on subject; contains(subject, …) and any attendee matching are not supported there and
 * stay in-process. Everything expressed here is re-checked in-process anyway, which is what makes
 * dropping the whole $filter on a Graph 400 safe rather than silently lossy.
 */
export function buildEventGraphFilter(input: {
  subject?: SubjectFilter;
  categories?: string[];
}): string | undefined {
  const clauses: string[] = [];
  // calendarView accepts one category comparison, so only the first is pushed down. That is still
  // a correct narrowing rather than a partial answer: events carrying every requested category are
  // a subset of those carrying the first, and matchesFilters requires all of them.
  const category = input.categories?.map((value) => value.trim()).find((value) => value !== '');
  if (category !== undefined) {
    clauses.push(`categories/any(c:c eq '${escapeODataString(category)}')`);
  }
  if (input.subject !== undefined && 'startsWith' in input.subject) {
    clauses.push(`startswith(subject,'${escapeODataString(input.subject.startsWith)}')`);
  }
  return clauses.length === 0 ? undefined : clauses.join(' and ');
}
