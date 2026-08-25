import * as z from 'zod';

export const RelativeRangeSchema = z.union([
  z.literal('today').describe('00:00:00.000 through 23:59:59.999 today in the mailbox timezone.'),
  z
    .literal('tomorrow')
    .describe('The same full-day window as today, shifted one calendar day forward.'),
  z
    .literal('yesterday')
    .describe('The same full-day window as today, shifted one calendar day back.'),
  z
    .literal('thisWeek')
    .describe('Monday 00:00:00.000 through Sunday 23:59:59.999 of the ISO week containing now.'),
  z.literal('nextWeek').describe('The ISO week (Monday–Sunday) after thisWeek.'),
  z.literal('lastWeek').describe('The ISO week (Monday–Sunday) before thisWeek.'),
  z
    .literal('thisMonth')
    .describe(
      'The 1st 00:00:00.000 through the last day 23:59:59.999 of the current calendar month.',
    ),
  z.literal('nextMonth').describe('The next calendar month, first through last day.'),
  z.literal('lastMonth').describe('The previous calendar month, first through last day.'),
  z
    .literal('thisYear')
    .describe(
      '1 January 00:00:00.000 through 31 December 23:59:59.999 of the current calendar year.',
    ),
  z.literal('nextYear').describe('The next calendar year, 1 January through 31 December.'),
  z.literal('lastYear').describe('The previous calendar year, 1 January through 31 December.'),
  z.literal('next7Days').describe('Rolling window from now forward 7 days.'),
  z.literal('next30Days').describe('Rolling window from now forward 30 days.'),
  z.literal('next90Days').describe('Rolling window from now forward 90 days.'),
  z.literal('past7Days').describe('Rolling window from 7 days ago through now.'),
  z.literal('past30Days').describe('Rolling window from 30 days ago through now.'),
]);
