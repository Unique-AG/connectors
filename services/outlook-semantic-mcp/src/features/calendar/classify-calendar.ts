import type { CalendarRef, GraphCalendar } from './calendar.schemas';

export function classifyCalendar(calendar: GraphCalendar, callerEmail: string): CalendarRef {
  const ownerEmail = calendar.owner?.address ?? null;
  const isOwn = ownerEmail !== null && ownerEmail.toLowerCase() === callerEmail.toLowerCase();
  const accessPath: CalendarRef['accessPath'] =
    !isOwn && calendar.isDefaultCalendar === true ? 'ownerMailbox' : 'ownMailbox';

  return {
    calendarId: calendar.id,
    name: calendar.name ?? 'Calendar',
    ownerEmail,
    ownerName: calendar.owner?.name ?? null,
    isOwn,
    canEdit: calendar.canEdit ?? false,
    canViewPrivateItems: calendar.canViewPrivateItems ?? false,
    accessPath,
  };
}
