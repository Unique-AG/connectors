import type { GraphScheduleInformation } from '../calendar.schemas';

export interface WorkingHours {
  daysOfWeek: string[];
  startTime: string | null;
  endTime: string | null;
  timeZone: string | null;
}

export function mapGraphWorkingHoursToWorkingHours(
  hours: GraphScheduleInformation['workingHours'],
): WorkingHours | null {
  if (hours === undefined || hours === null) {
    return null;
  }
  return {
    daysOfWeek: hours.daysOfWeek ?? [],
    startTime: hours.startTime ?? null,
    endTime: hours.endTime ?? null,
    timeZone: hours.timeZone?.name ?? null,
  };
}
