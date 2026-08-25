import type { CalendarRef, GraphCalendar } from './calendar.schemas';

export function classifyCalendar(
  calendar: GraphCalendar,
  callerEmail: string,
  accessPathOverride?: CalendarRef['accessPath'],
): CalendarRef {
  const ownerEmail = calendar.owner?.address ?? null;
  const isOwn = ownerEmail !== null && ownerEmail.toLowerCase() === callerEmail.toLowerCase();
  const ownerPrimary = calendar.isDefaultCalendar === true || calendar.isTallyingResponses === true;
  const accessPath: CalendarRef['accessPath'] =
    accessPathOverride ??
    (!isOwn && ownerEmail !== null && ownerPrimary ? 'ownerMailbox' : 'ownMailbox');

  return {
    calendarId: calendar.id,
    name: calendar.name ?? '',
    ownerEmail,
    ownerName: calendar.owner?.name ?? null,
    isOwn: accessPathOverride === 'ownerMailbox' ? false : isOwn,
    canEdit: calendar.canEdit ?? false,
    canViewPrivateItems: calendar.canViewPrivateItems ?? false,
    accessPath,
  };
}
