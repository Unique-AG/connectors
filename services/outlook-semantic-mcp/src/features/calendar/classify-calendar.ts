import { CalendarRef, type GraphCalendar } from './calendar.schemas';

export function classifyCalendar(input: {
  calendar: GraphCalendar;
  callerEmail: string;
  accessPathOverride?: CalendarRef['accessPath'];
}): CalendarRef {
  const ownerEmail = input.calendar.owner?.address ?? null;
  const isOwn = ownerEmail !== null && ownerEmail.toLowerCase() === input.callerEmail.toLowerCase();
  const ownerPrimary =
    input.calendar.isDefaultCalendar === true || input.calendar.isTallyingResponses === true;
  const accessPath: CalendarRef['accessPath'] =
    input.accessPathOverride ??
    (!isOwn && ownerEmail !== null && ownerPrimary ? 'ownerMailbox' : 'ownMailbox');

  return {
    calendarId: input.calendar.id,
    name: input.calendar.name ?? '',
    ownerEmail,
    ownerName: input.calendar.owner?.name ?? null,
    isOwn: input.accessPathOverride === 'ownerMailbox' ? false : isOwn,
    canEdit: input.calendar.canEdit ?? false,
    canViewPrivateItems: input.calendar.canViewPrivateItems ?? false,
    accessPath,
  };
}
