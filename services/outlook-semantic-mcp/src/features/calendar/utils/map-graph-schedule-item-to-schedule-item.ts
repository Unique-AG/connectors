import type { GraphScheduleItem } from '../calendar.schemas';

export interface ScheduleItem {
  status: string | null;
  subject: string | null;
  location: string | null;
  isPrivate: boolean;
  start: { dateTime: string; timeZone: string | null };
  end: { dateTime: string; timeZone: string | null };
}

export function mapGraphScheduleItemToScheduleItem(item: GraphScheduleItem): ScheduleItem {
  const isPrivate = item.isPrivate === true;
  return {
    status: item.status ?? null,
    subject: isPrivate ? null : (item.subject ?? null),
    location: isPrivate ? null : (item.location ?? null),
    isPrivate,
    start: {
      dateTime: item.start?.dateTime ?? '',
      timeZone: item.start?.timeZone ?? null,
    },
    end: {
      dateTime: item.end?.dateTime ?? '',
      timeZone: item.end?.timeZone ?? null,
    },
  };
}
