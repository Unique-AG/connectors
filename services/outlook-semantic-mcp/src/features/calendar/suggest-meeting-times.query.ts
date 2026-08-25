import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import { GetMailboxTimezoneQuery } from '~/features/user-utils/get-mailbox-timezone.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import {
  type RelativeRange,
  type ResolvedWindow,
  resolveQueryWindow,
  toGraphInstant,
} from '~/utils/relative-range';
import { resolveIanaTimezone } from '~/utils/resolve-iana-timezone';
import {
  GraphFindMeetingTimesResponseSchema,
  type GraphMeetingTimeSuggestion,
} from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
} from './utils/calendar-graph-errors';
import { findMeetingTimesPath, isSmtpAddress } from './utils/calendar-graph-path';
import { toGraphDateTimeTimeZone } from './utils/to-graph-date-time-time-zone';

const UTC = 'UTC';
const MAX_ATTENDEES = 20;
const MAX_CANDIDATES = 20;
const MAX_WINDOW_DAYS = 62;
const DEFAULT_DURATION_MINUTES = 30;
const DEFAULT_MAX_CANDIDATES = 5;
const DEFAULT_MIN_ATTENDEE_PERCENTAGE = 50;

export type ActivityDomain = 'work' | 'personal' | 'unrestricted';

interface AttendeeAvailability {
  email: string | null;
  availability: string | null;
}

export interface MeetingTimeSuggestion {
  start: { dateTime: string; timeZone: string | null };
  end: { dateTime: string; timeZone: string | null };
  confidence: number | null;
  organizerAvailability: string | null;
  suggestionReason: string | null;
  attendeeAvailability: AttendeeAvailability[];
}

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
    private readonly getMailboxTimezoneQuery: GetMailboxTimezoneQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: SuggestMeetingTimesQueryInput,
  ): Promise<SuggestMeetingTimesQueryOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const mailboxTimeZone = await this.getMailboxTimezoneQuery.run(userProfileId);
    const mappedIana =
      mailboxTimeZone === undefined ? undefined : resolveIanaTimezone(mailboxTimeZone);
    const ianaTimeZone = mappedIana ?? UTC;
    const outlookTimeZone =
      mailboxTimeZone !== undefined && mappedIana !== undefined ? mailboxTimeZone : UTC;
    const notes: string[] = [];
    if (mailboxTimeZone === undefined) {
      notes.push('Mailbox timezone was unavailable; times are requested in UTC.');
    } else if (mappedIana === undefined) {
      notes.push(
        `Mailbox timezone "${mailboxTimeZone}" could not be mapped to IANA; relative windows are resolved in UTC.`,
      );
    }

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
    if (isWindowTooLong(resolvedWindow)) {
      return {
        success: false,
        message: `Meeting times can only be suggested for a window shorter than ${MAX_WINDOW_DAYS} days. Use today, thisWeek, nextWeek, or next7Days.`,
        suggestionNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow,
      };
    }
    const attendees = uniqueAttendees(input.attendees ?? []);
    if ((input.attendees?.length ?? 0) > 0 && attendees.length === 0) {
      return {
        success: false,
        message: 'At least one valid attendee SMTP address is required.',
        suggestionNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow,
      };
    }
    if (attendees.length > MAX_ATTENDEES) {
      return {
        success: false,
        message: `This tool accepts at most ${MAX_ATTENDEES} attendees. Narrow the list.`,
        suggestionNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow,
      };
    }
    const mailbox = input.mailbox ?? userProfile.email;
    if (!isSmtpAddress(mailbox)) {
      return {
        success: false,
        message: 'mailbox must be an SMTP address.',
        resolvedWindow,
      };
    }

    const durationMinutes = input.durationMinutes ?? DEFAULT_DURATION_MINUTES;
    const maxCandidates = input.maxCandidates ?? DEFAULT_MAX_CANDIDATES;
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const startTime = toGraphDateTimeTimeZone({
      iso: resolvedWindow.startDateTime,
      ianaTimeZone,
      windowsTimeZone: outlookTimeZone,
    });
    const endTime = toGraphDateTimeTimeZone({
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
        .map(toSuggestion)
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

function isWindowTooLong(window: ResolvedWindow): boolean {
  const duration = Temporal.Instant.from(window.startDateTime).until(
    Temporal.Instant.from(window.endDateTime),
  );
  return Temporal.Duration.compare(duration, { days: MAX_WINDOW_DAYS }) >= 0;
}

function uniqueAttendees(attendees: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const attendee of attendees) {
    const trimmed = attendee.trim();
    const key = trimmed.toLowerCase();
    if (!isSmtpAddress(trimmed) || seen.has(key)) {
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

function toSuggestion(item: GraphMeetingTimeSuggestion): MeetingTimeSuggestion {
  return {
    start: {
      dateTime: item.meetingTimeSlot?.start?.dateTime ?? '',
      timeZone: item.meetingTimeSlot?.start?.timeZone ?? null,
    },
    end: {
      dateTime: item.meetingTimeSlot?.end?.dateTime ?? '',
      timeZone: item.meetingTimeSlot?.end?.timeZone ?? null,
    },
    confidence: item.confidence ?? null,
    organizerAvailability: item.organizerAvailability ?? null,
    suggestionReason: item.suggestionReason ?? null,
    attendeeAvailability: (item.attendeeAvailability ?? []).map((entry) => ({
      email: entry.attendee?.emailAddress?.address ?? null,
      availability: entry.availability ?? null,
    })),
  };
}
