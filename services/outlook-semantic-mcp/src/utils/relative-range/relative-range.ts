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

export const RELATIVE_RANGE_DESCRIPTIONS: Record<RelativeRange, string> = {
  today: '00:00:00.000 through 23:59:59.999 today in the mailbox timezone.',
  tomorrow: 'The same full-day window as today, shifted one calendar day forward.',
  yesterday: 'The same full-day window as today, shifted one calendar day back.',
  thisWeek: 'Monday 00:00:00.000 through Sunday 23:59:59.999 of the ISO week containing now.',
  nextWeek: 'The ISO week (Monday–Sunday) after thisWeek.',
  lastWeek: 'The ISO week (Monday–Sunday) before thisWeek.',
  thisMonth:
    'The 1st 00:00:00.000 through the last day 23:59:59.999 of the current calendar month.',
  nextMonth: 'The next calendar month, first through last day.',
  lastMonth: 'The previous calendar month, first through last day.',
  thisYear: '1 January 00:00:00.000 through 31 December 23:59:59.999 of the current calendar year.',
  nextYear: 'The next calendar year, 1 January through 31 December.',
  lastYear: 'The previous calendar year, 1 January through 31 December.',
  next7Days: 'Rolling window from now forward 7 days.',
  next30Days: 'Rolling window from now forward 30 days.',
  next90Days: 'Rolling window from now forward 90 days.',
  past7Days: 'Rolling window from 7 days ago through now.',
  past30Days: 'Rolling window from 30 days ago through now.',
};
