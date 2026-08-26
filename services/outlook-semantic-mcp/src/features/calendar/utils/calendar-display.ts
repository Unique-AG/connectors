/** Collapses whitespace so a pasted multi-line subject cannot reflow an elicitation prompt. */
export function oneLine(value: string): string {
  return value.replaceAll(/\s+/g, ' ').trim();
}

export interface CalendarDisplay {
  name: string;
  isDefaultCalendar: boolean;
  isOwn: boolean;
  ownerEmail: string | null;
  ownerName: string | null;
}

/**
 * Names the calendar the way the user recognises it. Deliberately reports the owner rather than
 * CalendarRef.mailbox: for a calendar shared with the signed-in user the mailbox is their own, so
 * showing it would read as if the event were landing on their personal calendar.
 */
export function describeCalendar(calendar: CalendarDisplay): string {
  const name = oneLine(calendar.name) === '' ? 'Calendar' : oneLine(calendar.name);
  if (calendar.isOwn) {
    return calendar.isDefaultCalendar
      ? `"${name}" — your primary calendar`
      : `"${name}" — your calendar`;
  }
  const owner =
    calendar.ownerName !== null && calendar.ownerEmail !== null
      ? `${oneLine(calendar.ownerName)} (${calendar.ownerEmail})`
      : (calendar.ownerEmail ?? calendar.ownerName ?? 'another mailbox');
  return calendar.isDefaultCalendar
    ? `"${name}" — the primary calendar of ${owner}`
    : `"${name}" — shared by ${owner}`;
}
