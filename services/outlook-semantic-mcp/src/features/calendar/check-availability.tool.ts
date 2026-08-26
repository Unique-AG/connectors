import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { CheckAvailabilityQuery } from './check-availability.query';
import { META } from './check-availability-tool.meta';
import {
  ConsentRequiredSchema,
  EventDateTimeSchema,
  ResolvedWindowSchema,
} from './utils/calendar-output.schema';
import { BUSY_STATUSES } from './utils/decode-availability-view';
import { GraphScheduleDateRangeSchema } from './utils/graph-schedule-date-range.schema';
import { smtpAddress } from './utils/smtp-address.schema';

export const CheckAvailabilityInputSchema = z.object({
  attendees: z
    .array(
      smtpAddress(
        'SMTP address of a person, distribution list, or room to check. Include the signed-in user to see their own free/busy.',
      ),
    )
    .min(1)
    .max(20)
    .describe(
      'People to check. Maximum 20 addresses per call. Include the signed-in user when asking about their own availability.',
    ),
  dateRange: GraphScheduleDateRangeSchema.describe(
    'Time window to check. Prefer rangeType relative with a documented range. Must be shorter than 62 days. thisYear, nextYear, lastYear, and next90Days are rejected.',
  ),
  mailbox: smtpAddress(
    'SMTP address of the mailbox whose calendar is used for the free/busy lookup. Omit to use the signed-in user. Use a delegated mailbox only when checking free/busy as that mailbox.',
  ).optional(),
  intervalMinutes: z
    .number()
    .int()
    .min(5)
    .max(1440)
    .optional()
    .describe(
      'Length of each availabilityView slot in minutes. Default 30. Minimum 5, maximum 1440.',
    ),
});

const BusyBlockSchema = z.object({
  status: z
    .enum(BUSY_STATUSES)
    .describe(
      'Merged availabilityView status: tentative, busy, oof, workingElsewhere, or unknown. Free slots are omitted.',
    ),
  startDateTime: z
    .string()
    .describe('Inclusive start of this busy block, including timezone offset.'),
  endDateTime: z.string().describe('Exclusive end of this busy block, including timezone offset.'),
});

const ScheduleItemSchema = z.object({
  status: z
    .string()
    .nullable()
    .describe('Free/busy status of this item: free, tentative, busy, oof, or workingElsewhere.'),
  subject: z
    .string()
    .nullable()
    .describe(
      'Item subject when the caller has detail-level permission. Null when Graph omitted it or isPrivate is true — do not invent one.',
    ),
  location: z
    .string()
    .nullable()
    .describe(
      'Item location when the caller has detail-level permission. Null when omitted or private.',
    ),
  isPrivate: z
    .boolean()
    .describe(
      'True when Graph marked the item private. Subject and location are then redacted even if a value was present.',
    ),
  start: EventDateTimeSchema.describe('Item start.'),
  end: EventDateTimeSchema.describe('Item end.'),
});

const WorkingHoursSchema = z.object({
  daysOfWeek: z
    .array(z.string().describe('Weekday name from Graph, e.g. monday.'))
    .describe('Days this person is marked as working.'),
  startTime: z
    .string()
    .nullable()
    .describe('Working-hours start as a time-of-day string from Graph, or null if omitted.'),
  endTime: z
    .string()
    .nullable()
    .describe('Working-hours end as a time-of-day string from Graph, or null if omitted.'),
  timeZone: z
    .string()
    .nullable()
    .describe('Windows timezone name attached to working hours, or null if omitted.'),
});

const PersonAvailabilitySchema = z.object({
  email: z.string().describe('SMTP address this availability belongs to.'),
  busyBlocks: z
    .array(BusyBlockSchema)
    .describe(
      'Non-free spans decoded from availabilityView. Use these for a compact busy picture. Free time is the complement within workingHours.',
    ),
  items: z
    .array(ScheduleItemSchema)
    .describe(
      'Individual schedule items. Subject and location appear only with detail-level permission; private items are redacted.',
    ),
  workingHours: WorkingHoursSchema.nullable().describe(
    "This person's working hours from Graph, or null when omitted.",
  ),
});

export const CheckAvailabilityOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when getSchedule ran. False when the window is too long, consent is missing, or Graph rejected the call.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  people: z
    .array(PersonAvailabilitySchema)
    .optional()
    .describe('Availability per requested address, in Graph return order.'),
  availabilityNotes: z
    .array(z.string())
    .optional()
    .describe(
      'Notes about timezone fallback or per-person Graph errors. Display after the results.',
    ),
  resolvedWindow: ResolvedWindowSchema.optional().describe(
    'The getSchedule window actually queried.',
  ),
  consentRequired: ConsentRequiredSchema.optional(),
});

@Injectable()
export class CheckAvailabilityTool {
  public constructor(private readonly checkAvailabilityQuery: CheckAvailabilityQuery) {}

  @Tool({
    name: 'check_availability',
    title: 'Check Availability',
    description:
      'Check free/busy for people, distribution lists, or rooms in a time window via Outlook getSchedule. Prefer dateRange.rangeType=relative with a documented range (today, thisWeek, nextWeek, next7Days); weeks start Monday. The window must be shorter than 62 days — do not use thisYear or next90Days. Pass at most 20 SMTP addresses in attendees; include the signed-in user to see their own free/busy. busyBlocks are decoded from availabilityView (free slots omitted). items may include subject and location only when the caller has detail-level permission; when isPrivate is true those fields are redacted. If availabilityNotes is present, show it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook.',
    parameters: CheckAvailabilityInputSchema,
    outputSchema: CheckAvailabilityOutputSchema,
    annotations: {
      title: 'Check Availability',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async checkAvailability(
    input: z.infer<typeof CheckAvailabilityInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof CheckAvailabilityOutputSchema>> {
    const { dateRange, ...filters } = CheckAvailabilityInputSchema.parse(input);
    return this.checkAvailabilityQuery.run(extractUserProfileId(request), {
      ...filters,
      ...(dateRange.rangeType === 'relative'
        ? { range: dateRange.range }
        : { startDateTime: dateRange.startDateTime, endDateTime: dateRange.endDateTime }),
    });
  }
}
