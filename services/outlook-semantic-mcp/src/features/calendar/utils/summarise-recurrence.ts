interface RecurrencePattern {
  type?: string;
  interval?: number;
  daysOfWeek?: string[];
}

const DAY_LABELS: Record<string, string> = {
  sunday: 'Sunday',
  monday: 'Monday',
  tuesday: 'Tuesday',
  wednesday: 'Wednesday',
  thursday: 'Thursday',
  friday: 'Friday',
  saturday: 'Saturday',
};

export function summariseRecurrence(pattern: RecurrencePattern | undefined): string | null {
  if (pattern?.type === undefined) {
    return null;
  }
  const interval = pattern.interval ?? 1;
  const days = (pattern.daysOfWeek ?? [])
    .map((day) => DAY_LABELS[day.toLowerCase()] ?? day)
    .join(', ');

  switch (pattern.type) {
    case 'daily':
      return interval === 1 ? 'Daily' : `Every ${interval} days`;
    case 'weekly':
      return interval === 1
        ? days === ''
          ? 'Weekly'
          : `Weekly on ${days}`
        : days === ''
          ? `Every ${interval} weeks`
          : `Every ${interval} weeks on ${days}`;
    case 'absoluteMonthly':
    case 'relativeMonthly':
      return interval === 1 ? 'Monthly' : `Every ${interval} months`;
    case 'absoluteYearly':
    case 'relativeYearly':
      return interval === 1 ? 'Yearly' : `Every ${interval} years`;
    default:
      return pattern.type;
  }
}
