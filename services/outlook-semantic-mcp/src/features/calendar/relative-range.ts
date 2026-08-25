export const RELATIVE_RANGES = [
  'today',
  'tomorrow',
  'yesterday',
  'thisWeek',
  'nextWeek',
  'lastWeek',
  'thisMonth',
  'nextMonth',
  'lastMonth',
  'thisYear',
  'nextYear',
  'lastYear',
  'next7Days',
  'next30Days',
  'next90Days',
  'past7Days',
  'past30Days',
] as const;

export type RelativeRange = (typeof RELATIVE_RANGES)[number];
