import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import {
  type CalendarMetricErrorType,
  CalendarMetricsService,
} from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { dateWindowFromSearchInput } from '~/utils/date-window-bucket';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import {
  type RelativeRange,
  type ResolvedWindow,
  resolveQueryWindow,
  toGraphInstant,
} from '~/utils/relative-range';
import { GraphFindMeetingTimesResponseSchema } from './calendar.schemas';
import { findMeetingTimesPath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  recoverCalendarGraphError,
} from './utils/calendar-observability';
import { isScheduleWindowTooLong } from './utils/graph-schedule-date-range.schema';
import {
  type MeetingTimeSuggestion,
  mapGraphMeetingTimeSuggestionToMeetingTimeSuggestion,
} from './utils/map-graph-meeting-time-suggestion-to-meeting-time-suggestion';
import { mapIsoToGraphDateTimeTimeZone } from './utils/map-iso-to-graph-date-time-time-zone';
import { SmtpAddressSchema, uniqueSmtpAddresses } from './utils/smtp-address.schema';

const MAX_ATTENDEES = 20;
const MAX_CANDIDATES = 20;
const DEFAULT_DURATION_MINUTES = 30;
const DEFAULT_MAX_CANDIDATES = 5;
const DEFAULT_MIN_ATTENDEE_PERCENTAGE = 50;

export type ActivityDomain = 'work' | 'personal' | 'unrestricted';

export interface SuggestMeetingTimesQueryInput {
  attendees?: string[];
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
  errorType?: CalendarMetricErrorType;
}

@Injectable()
export class SuggestMeetingTimesQuery {
  private readonly logger = new Logger(SuggestMeetingTimesQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly resolveMailboxTimezoneQuery: ResolveMailboxTimezoneQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: SuggestMeetingTimesQueryInput,
  ): Promise<SuggestMeetingTimesQueryOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({
      userProfileId: userProfileIdString,
      attendeeCount: input.attendees?.length ?? 0,
      range: input.range,
      msg: 'suggest_meeting_times started',
    });
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      operation: 'suggest_meeting_times',
    });
    return this.calendarMetrics.measureOperation(
      {
        operation: 'suggest_meeting_times',
        dateWindow: dateWindowFromSearchInput(input),
      },
      () => this.suggest(userProfileId, userProfileIdString, input),
    );
  }

  private async suggest(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
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
      this.logger.debug({
        userProfileId: userProfileIdString,
        mailbox: obfuscateEmail(userProfile.email),
        interpretation: resolved.window.interpretation,
        msg: 'suggest_meeting_times window entirely in the past',
      });
      return {
        success: false,
        message:
          'The window is entirely in the past. Use a future range such as today, tomorrow, thisWeek, or next7Days.',
        suggestionNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow: resolved.window,
        errorType: 'invalid',
      };
    }
    if (resolved.notes.length > 0) {
      this.logger.debug({
        userProfileId: userProfileIdString,
        mailbox: obfuscateEmail(userProfile.email),
        msg: 'suggest_meeting_times start clamped to now',
      });
    }
    notes.push(...resolved.notes);
    const resolvedWindow = resolved.window;
    this.logger.debug({
      userProfileId: userProfileIdString,
      mailbox: obfuscateEmail(userProfile.email),
      ianaTimeZone,
      outlookTimeZone,
      interpretation: resolvedWindow.interpretation,
      msg: 'suggest_meeting_times window',
    });
    assert.ok(
      !isScheduleWindowTooLong(resolvedWindow.startDateTime, resolvedWindow.endDateTime),
      'dateRange must already be shorter than 62 days',
    );
    const attendees = uniqueSmtpAddresses(input.attendees ?? []);
    assert.ok(
      attendees.length <= MAX_ATTENDEES,
      'attendees must already be at most 20 SMTP addresses',
    );
    assert.ok(
      SmtpAddressSchema.safeParse(userProfile.email).success,
      'signed-in user email must already be an SMTP address',
    );
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox: userProfile.email,
      operation: 'suggest_meeting_times',
    });

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
        .api(findMeetingTimesPath(userProfile.email))
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
        userProfileId: userProfileIdString,
        mailbox: obfuscateEmail(userProfile.email),
        attendeeCount: attendees.length,
        returned: suggestions.length,
        msg: 'suggest_meeting_times findMeetingTimes',
      });
      if (suggestions.length === 0) {
        this.logger.debug({
          userProfileId: userProfileIdString,
          mailbox: obfuscateEmail(userProfile.email),
          emptySuggestionsReason: emptyReason,
          msg: 'suggest_meeting_times no slots',
        });
      }
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
      return {
        ...recoverCalendarGraphError({
          error,
          logger: this.logger,
          userProfileId: userProfileIdString,
          mailbox: userProfile.email,
          callerEmail: userProfile.email,
          operation: 'suggest_meeting_times',
          deniedDelegatedMessage: `Could not suggest times from mailbox ${userProfile.email}.`,
        }),
        suggestionNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow,
      };
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
