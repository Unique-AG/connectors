import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { DateRangeSchema } from '~/utils/relative-range';
import { SuggestMeetingTimesQuery } from './suggest-meeting-times.query';
import { META } from './suggest-meeting-times-tool.meta';
import { SMTP_ADDRESS } from './utils/calendar-graph-path';

function smtpAddress(description: string) {
  return z.string().regex(SMTP_ADDRESS, 'Must be an SMTP address').describe(description);
}

export const SuggestMeetingTimesInputSchema = z.object({
  attendees: z
    .array(
      smtpAddress(
        'SMTP address of a required attendee. Omit the whole array to find slots for the organizer only.',
      ),
    )
    .max(20)
    .optional()
    .describe(
      'People who must be free. Maximum 20. Omit to search only the organizer mailbox working hours.',
    ),
  dateRange: DateRangeSchema.describe(
    'Future window in which to search for slots. Prefer rangeType relative (today, tomorrow, thisWeek, nextWeek, next7Days). Must be shorter than 62 days. Past-only ranges (yesterday, lastWeek, past30Days) are rejected; if the start is already past, suggestions begin from now.',
  ),
  durationMinutes: z
    .number()
    .int()
    .min(5)
    .max(1440)
    .optional()
    .describe('Meeting length in minutes. Default 30. Minimum 5, maximum 1440.'),
  mailbox: smtpAddress(
    'SMTP address of the organizer mailbox findMeetingTimes is called on. Omit to use the signed-in user. Use a delegated mailbox only when suggesting times as that mailbox.',
  ).optional(),
  maxCandidates: z
    .number()
    .int()
    .min(1)
    .max(20)
    .optional()
    .describe('Maximum number of ranked slots to return. Default 5. Maximum 20.'),
  activityDomain: z
    .enum(['work', 'personal', 'unrestricted'])
    .optional()
    .describe(
      'work (default) stays inside mailbox working hours. personal adds Saturday and Sunday. unrestricted uses all hours.',
    ),
  isOrganizerOptional: z
    .boolean()
    .optional()
    .describe('True when the organizer does not have to be free. Default false.'),
  minimumAttendeePercentage: z
    .number()
    .min(0)
    .max(100)
    .optional()
    .describe(
      'Minimum average chance of attendance (0–100) for a slot to be returned. Default 50.',
    ),
});

const DateTimeSchema = z.object({
  dateTime: z
    .string()
    .describe('Local date and time of the boundary as returned by Graph, without a trailing Z.'),
  timeZone: z
    .string()
    .nullable()
    .describe('Windows or IANA timezone Graph attached to this boundary, or null if omitted.'),
});

const AttendeeAvailabilitySchema = z.object({
  email: z.string().nullable().describe('SMTP address of the attendee, or null if omitted.'),
  availability: z
    .string()
    .nullable()
    .describe('Free/busy at this slot: free, tentative, busy, oof, workingElsewhere, or unknown.'),
});

const MeetingTimeSuggestionSchema = z.object({
  start: DateTimeSchema.describe('Suggested slot start.'),
  end: DateTimeSchema.describe('Suggested slot end.'),
  confidence: z
    .number()
    .nullable()
    .describe(
      'Average chance (0–100) that attendees are free. Null when Graph omitted it. Higher is better.',
    ),
  organizerAvailability: z
    .string()
    .nullable()
    .describe('Organizer free/busy at this slot, or null if omitted.'),
  suggestionReason: z
    .string()
    .nullable()
    .describe('Graph explanation for this slot. State it when present.'),
  attendeeAvailability: z
    .array(AttendeeAvailabilitySchema)
    .describe('Per-attendee free/busy at this slot.'),
});

export const SuggestMeetingTimesOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when findMeetingTimes ran. False when consent is missing or Graph rejected the call.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  suggestions: z
    .array(MeetingTimeSuggestionSchema)
    .optional()
    .describe('Ranked slots, highest confidence first. Empty when Graph found none.'),
  emptySuggestionsReason: z
    .string()
    .nullable()
    .optional()
    .describe(
      'Why Graph found no slots: attendeesUnavailable, attendeesUnavailableOrUnknown, locationsUnavailable, organizerUnavailable, or unknown. Null when slots were returned or Graph omitted a reason.',
    ),
  suggestionNotes: z
    .array(z.string())
    .optional()
    .describe('Notes about timezone fallback or empty results. Display after the results.'),
  resolvedWindow: z
    .object({
      startDateTime: z
        .string()
        .describe('Absolute start sent to Graph, including timezone offset.'),
      endDateTime: z.string().describe('Absolute end sent to Graph, including timezone offset.'),
      timeZone: z
        .string()
        .describe(
          'IANA timezone the window was resolved in, or UTC when the mailbox timezone was unavailable.',
        ),
      serverCurrentDateTime: z
        .string()
        .describe('Server clock in that timezone when the window was resolved, including offset.'),
      interpretation: z
        .string()
        .describe('Human description of the window. State this when a relative range was used.'),
    })
    .optional()
    .describe('The findMeetingTimes window actually queried.'),
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

@Injectable()
export class SuggestMeetingTimesTool {
  public constructor(private readonly suggestMeetingTimesQuery: SuggestMeetingTimesQuery) {}

  @Tool({
    name: 'suggest_meeting_times',
    title: 'Suggest Meeting Times',
    description:
      'Suggest ranked meeting times from Outlook findMeetingTimes for the organizer and optional required attendees. Prefer dateRange.rangeType=relative with a future range (today, tomorrow, thisWeek, nextWeek, next7Days); weeks start Monday. The window must be shorter than 62 days; past-only ranges are rejected and a start that is already past is clamped to now. Default duration is 30 minutes and activityDomain is work (mailbox working hours). Omit attendees to find slots for the organizer only. If emptySuggestionsReason is present, explain it and suggest widening the window. If suggestionNotes is present, show it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook.',
    parameters: SuggestMeetingTimesInputSchema,
    outputSchema: SuggestMeetingTimesOutputSchema,
    annotations: {
      title: 'Suggest Meeting Times',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async suggestMeetingTimes(
    input: z.infer<typeof SuggestMeetingTimesInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof SuggestMeetingTimesOutputSchema>> {
    const { dateRange, ...filters } = SuggestMeetingTimesInputSchema.parse(input);
    return this.suggestMeetingTimesQuery.run(extractUserProfileId(request), {
      ...filters,
      ...(dateRange.rangeType === 'relative'
        ? { range: dateRange.range }
        : { startDateTime: dateRange.startDateTime, endDateTime: dateRange.endDateTime }),
    });
  }
}
