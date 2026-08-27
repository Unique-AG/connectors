import { CalendarRef, type GraphCalendar } from '../calendar.schemas';

export function mapGraphCalendarToCalendarRef(input: {
  calendar: GraphCalendar;
  userProfileEmail: string;
}): CalendarRef {
  const ownerEmail = input.calendar.owner?.address ?? null;
  const userProfileEmail = input.userProfileEmail.toLowerCase();

  return {
    calendarId: input.calendar.id,
    name: input.calendar.name ?? '',
    ownerEmail,
    ownerName: input.calendar.owner?.name ?? null,
    isOwn: ownerEmail !== null && ownerEmail.toLowerCase() === userProfileEmail,
    isDefaultCalendar: input.calendar.isDefaultCalendar ?? false,
    canEdit: input.calendar.canEdit ?? false,
    canViewPrivateItems: input.calendar.canViewPrivateItems ?? false,
  };
}
