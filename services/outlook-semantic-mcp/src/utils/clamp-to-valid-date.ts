// LLMs occasionally produce invalid dates (e.g. 2024-02-30) when generating
// search filter values. Rather than surfacing a validation error to the user,
// we silently clamp the day to the last valid day of that month so the query
// can still execute and return meaningful results.
export function clampToValidDate(val: unknown): unknown {
  if (typeof val !== 'string') {
    return val;
  }
  const match = val.match(/^(\d{4})-(\d{2})-(\d{2})(T.*)$/);
  if (!match) {
    return val;
  }
  const [, year, month, day, time] = match;
  const lastDay = new Date(Number(year), Number(month), 0).getDate();
  if (Number(day) <= lastDay) {
    return val;
  }
  return `${year}-${month}-${String(lastDay).padStart(2, '0')}${time}`;
}
