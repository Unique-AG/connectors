export type SubjectFilter = { startsWith: string } | { contains: string };

/**
 * OData escapes a single quote inside a string literal by doubling it. Subject text arrives from
 * tool input, so this is the same boundary concern as SmtpAddressSchema: without it a subject
 * containing an apostrophe either breaks the query or changes what it asks for.
 */
function escapeODataString(value: string): string {
  return value.replaceAll("'", "''");
}

/**
 * The server-side half of the event filters, currently subject alone. Attendee matching is not
 * supported by calendarView, and categories stay in-process for now, so both are left to
 * matchesFilters. Everything expressed here is re-checked in-process anyway, which is what makes
 * dropping the whole $filter on a Graph 400 safe rather than silently lossy.
 *
 * The null guard is part of the clause rather than an optimisation: calendarView answers 500, not
 * an empty match, when any event in the window has no subject.
 */
export function buildEventGraphFilter(input: { subject?: SubjectFilter }): string | undefined {
  if (input.subject === undefined) {
    return undefined;
  }
  const match =
    'startsWith' in input.subject
      ? `startswith(subject,'${escapeODataString(input.subject.startsWith)}')`
      : `contains(subject,'${escapeODataString(input.subject.contains)}')`;
  return `subject ne null and ${match}`;
}
