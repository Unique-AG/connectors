import { CalendarRef, type GraphCalendar } from '../calendar.schemas';

export function mapGraphCalendarToCalendarRef(input: {
  calendar: GraphCalendar;
  callerEmail: string;
  /**
   * The mailbox this calendar was just listed from. Passed in rather than derived: it is the one
   * mailbox the calendarId resolves in, and deriving it from the payload is what makes a shared
   * calendar unreadable. See CalendarRef.mailbox.
   */
  mailboxEmail: string;
}): CalendarRef {
  const ownerEmail = input.calendar.owner?.address ?? null;

  return {
    calendarId: input.calendar.id,
    name: input.calendar.name ?? '',
    mailbox: input.mailboxEmail,
    ownerEmail,
    ownerName: input.calendar.owner?.name ?? null,
    isOwn: ownerEmail !== null && ownerEmail.toLowerCase() === input.callerEmail.toLowerCase(),
    canEdit: input.calendar.canEdit ?? false,
    canViewPrivateItems: input.calendar.canViewPrivateItems ?? false,
  };
}
