import type { CalendarRef, GraphCalendar } from './calendar.schemas';

export function classifyCalendar(calendar: GraphCalendar, callerEmail: string): CalendarRef {
  const ownerEmail = calendar.owner?.address ?? null;
  const isOwn = ownerEmail !== null && ownerEmail.toLowerCase() === callerEmail.toLowerCase();
  const ownerPrimary = calendar.isDefaultCalendar === true || calendar.isTallyingResponses === true;
  const accessPath: CalendarRef['accessPath'] =
    !isOwn && ownerEmail !== null && ownerPrimary ? 'ownerMailbox' : 'ownMailbox';

  return {
    calendarId: calendar.id,
    name: calendar.name ?? '',
    ownerEmail,
    ownerName: calendar.owner?.name ?? null,
    isOwn,
    canEdit: calendar.canEdit ?? false,
    canViewPrivateItems: calendar.canViewPrivateItems ?? false,
    accessPath,
  };
}
