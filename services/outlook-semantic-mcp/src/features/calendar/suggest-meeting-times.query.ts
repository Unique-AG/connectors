import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import {
  type RelativeRange,
  type ResolvedWindow,
  resolveQueryWindow,
  toGraphInstant,
} from '~/utils/relative-range';
import { GraphFindMeetingTimesResponseSchema } from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
} from './utils/calendar-graph-errors';
import { findMeetingTimesPath } from './utils/calendar-graph-path';
import { isScheduleWindowTooLong } from './utils/graph-schedule-date-range.schema';
import {
  type MeetingTimeSuggestion,
  mapGraphMeetingTimeSuggestionToMeetingTimeSuggestion,
} from './utils/map-graph-meeting-time-suggestion-to-meeting-time-suggestion';
import { mapIsoToGraphDateTimeTimeZone } from './utils/map-iso-to-graph-date-time-time-zone';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

const MAX_ATTENDEES = 20;
const MAX_CANDIDATES = 20;
const DEFAULT_DURATION_MINUTES = 30;
const DEFAULT_MAX_CANDIDATES = 5;
const DEFAULT_MIN_ATTENDEE_PERCENTAGE = 50;

export type ActivityDomain = 'work' | 'personal' | 'unrestricted';

export interface SuggestMeetingTimesQueryInput {
  attendees?: string[];
  mailbox?: string;
  durationMinutes?: number;
  maxCandidates?: number;
  activityDomain?: ActivityDomain;
  isOrganizerOptional?: boolean;
  minimumAttendeePercentage?: number;
  range?: RelativeRange;
  startDateTime?: string;
  endDateTime?: string;
  now?: Temporal.ZonedDateTime;
}

export interface SuggestMeetingTimesQueryOutput {
  success: boolean;
  message: string;
  suggestions?: MeetingTimeSuggestion[];
  emptySuggestionsReason?: string | null;
  suggestionNotes?: string[];
  resolvedWindow?: ResolvedWindow;
  consentRequired?: boolean;
}

@Injectable()
export class SuggestMeetingTimesQuery {
  private readonly logger = new Logger(SuggestMeetingTimesQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly resolveMailboxTimezoneQuery: ResolveMailboxTimezoneQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: SuggestMeetingTimesQueryInput,
  ): Promise<SuggestMeetingTimesQueryOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const {
      ianaTimeZone,
      outlookTimeZone,
      notes: timezoneNotes,
    } = await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const notes = [...timezoneNotes];

    const clock = input.now ?? Temporal.Now.zonedDateTimeISO(ianaTimeZone);
    const resolved = clampSuggestionWindow({
      window: resolveQueryWindow({
        range: input.range,
        startDateTime: input.startDateTime,
        endDateTime: input.endDateTime,
        now: clock,
      }),
      now: clock,
    });
    if (resolved.tooLate) {
      return {
        success: false,
        message:
          'The window is entirely in the past. Use a future range such as today, tomorrow, thisWeek, or next7Days.',
        suggestionNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow: resolved.window,
      };
    }
    notes.push(...resolved.notes);
    const resolvedWindow = resolved.window;
    assert.ok(
      !isScheduleWindowTooLong(resolvedWindow.startDateTime, resolvedWindow.endDateTime),
      'dateRange must already be shorter than 62 days',
    );
    const attendees = uniqueAttendees(input.attendees ?? []);
    assert.ok(
      attendees.length <= MAX_ATTENDEES,
      'attendees must already be at most 20 SMTP addresses',
    );
    const mailbox = input.mailbox ?? userProfile.email;
    assert.ok(
      SmtpAddressSchema.safeParse(mailbox).success,
      'mailbox must already be an SMTP address',
    );

    const durationMinutes = input.durationMinutes ?? DEFAULT_DURATION_MINUTES;
    const maxCandidates = input.maxCandidates ?? DEFAULT_MAX_CANDIDATES;
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const startTime = mapIsoToGraphDateTimeTimeZone({
      iso: resolvedWindow.startDateTime,
      ianaTimeZone,
      windowsTimeZone: outlookTimeZone,
    });
    const endTime = mapIsoToGraphDateTimeTimeZone({
      iso: resolvedWindow.endDateTime,
      ianaTimeZone,
      windowsTimeZone: outlookTimeZone,
    });

    try {
      const raw = await client
        .api(findMeetingTimesPath(mailbox))
        .header('Prefer', `outlook.timezone="${outlookTimeZone}"`)
        .post({
          attendees: attendees.map((address) => ({
            type: 'required',
            emailAddress: { address },
          })),
          timeConstraint: {
            activityDomain: input.activityDomain ?? 'work',
            timeSlots: [{ start: startTime, end: endTime }],
          },
          meetingDuration: toIsoDuration(durationMinutes),
          maxCandidates,
          isOrganizerOptional: input.isOrganizerOptional ?? false,
          returnSuggestionReasons: true,
          minimumAttendeePercentage:
            input.minimumAttendeePercentage ?? DEFAULT_MIN_ATTENDEE_PERCENTAGE,
        });
      const parsed = GraphFindMeetingTimesResponseSchema.parse(raw);
      const suggestions = (parsed.meetingTimeSuggestions ?? [])
        .map(mapGraphMeetingTimeSuggestionToMeetingTimeSuggestion)
        .slice(0, MAX_CANDIDATES);
      const emptyReason = emptySuggestionsReason(parsed.emptySuggestionsReason);
      if (suggestions.length === 0 && emptyReason !== null) {
        notes.push(
          `Graph returned no slots: ${emptyReason}. Widen the window or relax constraints.`,
        );
      }
      this.logger.log({
        msg: 'suggest_meeting_times findMeetingTimes',
        attendeeCount: attendees.length,
        returned: suggestions.length,
      });
      return {
        success: true,
        message:
          suggestions.length === 0
            ? emptyReason === null
              ? 'No meeting times were suggested.'
              : `No meeting times were suggested (${emptyReason}).`
            : `Found ${suggestions.length} suggested time${suggestions.length === 1 ? '' : 's'}.`,
        suggestions,
        emptySuggestionsReason: emptyReason,
        suggestionNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow,
      };
    } catch (error) {
      if (isCalendarPermissionDeniedError(error)) {
        if (mailbox.toLowerCase() === userProfile.email.toLowerCase()) {
          return {
            success: false,
            message: new CalendarConsentRequiredError().message,
            consentRequired: true,
            resolvedWindow,
          };
        }
        return {
          success: false,
          message: `Could not suggest times from mailbox ${mailbox}.`,
          suggestionNotes: notes.length > 0 ? notes : undefined,
          resolvedWindow,
        };
      }
      throw error;
    }
  }
}

function clampSuggestionWindow(input: {
  window: ResolvedWindow;
  now: Temporal.ZonedDateTime;
}):
  | { tooLate: true; window: ResolvedWindow; notes: string[] }
  | { tooLate: false; window: ResolvedWindow; notes: string[] } {
  const start = Temporal.Instant.from(input.window.startDateTime);
  const end = Temporal.Instant.from(input.window.endDateTime);
  const now = input.now.toInstant();
  if (Temporal.Instant.compare(end, now) <= 0) {
    return { tooLate: true, window: input.window, notes: [] };
  }
  if (Temporal.Instant.compare(start, now) >= 0) {
    return { tooLate: false, window: input.window, notes: [] };
  }
  return {
    tooLate: false,
    window: {
      ...input.window,
      startDateTime: toGraphInstant(input.now),
      interpretation: `${input.window.interpretation}; start clamped to now because the original start was in the past`,
    },
    notes: ['The start of the window was in the past; suggestions start from now.'],
  };
}

function uniqueAttendees(attendees: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const attendee of attendees) {
    const trimmed = attendee.trim();
    const key = trimmed.toLowerCase();
    if (!SmtpAddressSchema.safeParse(trimmed).success || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(trimmed);
  }
  return result;
}

function toIsoDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  if (hours === 0) {
    return `PT${remaining}M`;
  }
  if (remaining === 0) {
    return `PT${hours}H`;
  }
  return `PT${hours}H${remaining}M`;
}

function emptySuggestionsReason(value: string | undefined): string | null {
  if (value === undefined || value.trim() === '') {
    return null;
  }
  return value;
}
