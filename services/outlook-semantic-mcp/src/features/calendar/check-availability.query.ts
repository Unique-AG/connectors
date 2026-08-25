import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { Temporal } from 'temporal-polyfill';
import { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import {
  type RelativeRange,
  type ResolvedWindow,
  resolveQueryWindow,
} from '~/utils/relative-range';
import { GraphGetScheduleResponseSchema, type GraphScheduleInformation } from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
  isGetScheduleTooManyEntriesError,
} from './utils/calendar-graph-errors';
import { getSchedulePath } from './utils/calendar-graph-path';
import {
  calendarTraceAttrs,
  calendarUserProfileId,
  logCalendarRecovered,
} from './utils/calendar-observability';
import { dateWindowFromSearchInput } from './utils/date-window-bucket';
import { type AvailabilityBlock, decodeAvailabilityView } from './utils/decode-availability-view';
import { isScheduleWindowTooLong } from './utils/graph-schedule-date-range.schema';
import {
  mapGraphScheduleItemToScheduleItem,
  type ScheduleItem,
} from './utils/map-graph-schedule-item-to-schedule-item';
import {
  mapGraphWorkingHoursToWorkingHours,
  type WorkingHours,
} from './utils/map-graph-working-hours-to-working-hours';
import { mapIsoToGraphDateTimeTimeZone } from './utils/map-iso-to-graph-date-time-time-zone';
import { SmtpAddressSchema } from './utils/smtp-address.schema';

const MAX_SCHEDULES = 20;
const DEFAULT_INTERVAL_MINUTES = 30;
const MAX_BUSY_BLOCKS_PER_PERSON = 100;
const MAX_ITEMS_PER_PERSON = 100;
const TOO_MANY_ENTRIES_MESSAGE =
  'This window has more than 1000 calendar entries in a slot. Narrow the date range and try again.';

export interface PersonAvailability {
  email: string;
  busyBlocks: AvailabilityBlock[];
  items: ScheduleItem[];
  workingHours: WorkingHours | null;
}

export interface CheckAvailabilityQueryInput {
  attendees: string[];
  mailbox?: string;
  intervalMinutes?: number;
  range?: RelativeRange;
  startDateTime?: string;
  endDateTime?: string;
  now?: Temporal.ZonedDateTime;
}

export interface CheckAvailabilityQueryOutput {
  success: boolean;
  message: string;
  people?: PersonAvailability[];
  availabilityNotes?: string[];
  resolvedWindow?: ResolvedWindow;
  consentRequired?: boolean;
}

@Injectable()
export class CheckAvailabilityQuery {
  private readonly logger = new Logger(CheckAvailabilityQuery.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly resolveMailboxTimezoneQuery: ResolveMailboxTimezoneQuery,
    private readonly calendarMetrics: CalendarMetricsService,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: CheckAvailabilityQueryInput,
  ): Promise<CheckAvailabilityQueryOutput> {
    const userProfileIdString = calendarUserProfileId(userProfileId);
    this.logger.debug({
      userProfileId: userProfileIdString,
      mailbox: input.mailbox,
      attendeeCount: input.attendees.length,
      range: input.range,
      msg: 'check_availability started',
    });
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox: input.mailbox,
      operation: 'check_availability',
    });
    return this.calendarMetrics.measureOperation(
      {
        operation: 'check_availability',
        dateWindow: dateWindowFromSearchInput(input),
      },
      (fail) => this.check(userProfileId, userProfileIdString, input, fail),
    );
  }

  private async check(
    userProfileId: UserProfileTypeID,
    userProfileIdString: string,
    input: CheckAvailabilityQueryInput,
    fail: (errorType: 'consent' | 'permission' | 'too_many_entries') => void,
  ): Promise<CheckAvailabilityQueryOutput> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const {
      ianaTimeZone,
      outlookTimeZone,
      notes: timezoneNotes,
    } = await this.resolveMailboxTimezoneQuery.run(userProfileId);
    const notes = [...timezoneNotes];

    const clock = input.now ?? Temporal.Now.zonedDateTimeISO(ianaTimeZone);
    const resolvedWindow = resolveQueryWindow({
      range: input.range,
      startDateTime: input.startDateTime,
      endDateTime: input.endDateTime,
      now: clock,
    });
    this.logger.debug({
      userProfileId: userProfileIdString,
      mailbox: input.mailbox ?? userProfile.email,
      ianaTimeZone,
      outlookTimeZone,
      interpretation: resolvedWindow.interpretation,
      msg: 'check_availability window',
    });
    const schedules = uniqueSchedules(input.attendees);
    assert.ok(
      schedules.length > 0 && schedules.length <= MAX_SCHEDULES,
      'attendees must already be a non-empty list of at most 20 SMTP addresses',
    );
    assert.ok(
      !isScheduleWindowTooLong(resolvedWindow.startDateTime, resolvedWindow.endDateTime),
      'dateRange must already be shorter than 62 days',
    );
    const mailbox = input.mailbox ?? userProfile.email;
    assert.ok(
      SmtpAddressSchema.safeParse(mailbox).success,
      'mailbox must already be an SMTP address',
    );
    calendarTraceAttrs({
      userProfileId: userProfileIdString,
      mailbox,
      operation: 'check_availability',
    });
    const intervalMinutes = input.intervalMinutes ?? DEFAULT_INTERVAL_MINUTES;
    const client = this.graphClientFactory.createClientForUser(userProfile.id);

    try {
      const raw = await client
        .api(getSchedulePath(mailbox))
        .header('Prefer', `outlook.timezone="${outlookTimeZone}"`)
        .post({
          schedules,
          startTime: mapIsoToGraphDateTimeTimeZone({
            iso: resolvedWindow.startDateTime,
            ianaTimeZone,
            windowsTimeZone: outlookTimeZone,
          }),
          endTime: mapIsoToGraphDateTimeTimeZone({
            iso: resolvedWindow.endDateTime,
            ianaTimeZone,
            windowsTimeZone: outlookTimeZone,
          }),
          availabilityViewInterval: intervalMinutes,
        });
      const parsed = GraphGetScheduleResponseSchema.parse(raw);
      const viewStart = Temporal.Instant.from(resolvedWindow.startDateTime).toZonedDateTimeISO(
        ianaTimeZone,
      );
      const people = parsed.value.map((item) =>
        this.toPersonAvailability({
          item,
          viewStart,
          intervalMinutes,
          notes,
          userProfileId: userProfileIdString,
          mailbox,
        }),
      );
      this.logger.log({
        userProfileId: userProfileIdString,
        mailbox,
        scheduleCount: schedules.length,
        returned: people.length,
        msg: 'check_availability getSchedule',
      });
      if (people.length === 0) {
        this.logger.debug({
          userProfileId: userProfileIdString,
          mailbox,
          msg: 'check_availability no availability returned',
        });
      }
      return {
        success: true,
        message:
          people.length === 0
            ? 'No availability was returned.'
            : `Checked availability for ${people.length} ${people.length === 1 ? 'person' : 'people'}.`,
        people,
        availabilityNotes: notes.length > 0 ? notes : undefined,
        resolvedWindow,
      };
    } catch (error) {
      if (isGetScheduleTooManyEntriesError(error)) {
        fail('too_many_entries');
        logCalendarRecovered(this.logger, {
          userProfileId: userProfileIdString,
          mailbox,
          outcome: 'too_many_entries',
          msg: 'check_availability too many calendar entries',
          err: error,
        });
        return {
          success: false,
          message: TOO_MANY_ENTRIES_MESSAGE,
          availabilityNotes: notes.length > 0 ? notes : undefined,
          resolvedWindow,
        };
      }
      if (isCalendarPermissionDeniedError(error)) {
        if (mailbox.toLowerCase() === userProfile.email.toLowerCase()) {
          fail('consent');
          logCalendarRecovered(this.logger, {
            userProfileId: userProfileIdString,
            mailbox,
            outcome: 'consent',
            msg: 'check_availability consent required',
            err: error,
          });
          return {
            success: false,
            message: new CalendarConsentRequiredError().message,
            consentRequired: true,
            resolvedWindow,
          };
        }
        fail('permission');
        logCalendarRecovered(this.logger, {
          userProfileId: userProfileIdString,
          mailbox,
          outcome: 'permission',
          msg: 'check_availability mailbox denied',
          err: error,
        });
        return {
          success: false,
          message: `Could not read availability from mailbox ${mailbox}.`,
          availabilityNotes: notes.length > 0 ? notes : undefined,
          resolvedWindow,
        };
      }
      throw error;
    }
  }

  private toPersonAvailability(input: {
    item: GraphScheduleInformation;
    viewStart: Temporal.ZonedDateTime;
    intervalMinutes: number;
    notes: string[];
    userProfileId: string;
    mailbox: string;
  }): PersonAvailability {
    const email = input.item.scheduleId ?? 'unknown';
    if (isTooManyEntries(input.item.error)) {
      this.logger.warn({
        userProfileId: input.userProfileId,
        mailbox: input.mailbox,
        scheduleId: email,
        msg: 'check_availability person too many entries',
      });
      input.notes.push(`${email}: ${TOO_MANY_ENTRIES_MESSAGE}`);
    } else if (input.item.error?.message !== undefined) {
      this.logger.warn({
        userProfileId: input.userProfileId,
        mailbox: input.mailbox,
        scheduleId: email,
        graphResponseCode: input.item.error.responseCode,
        msg: 'check_availability person error',
      });
      input.notes.push(`${email}: ${input.item.error.message}`);
    }
    const busyBlocks = decodeAvailabilityView({
      availabilityView: input.item.availabilityView ?? '',
      start: input.viewStart,
      intervalMinutes: input.intervalMinutes,
    });
    const items = (input.item.scheduleItems ?? []).map(mapGraphScheduleItemToScheduleItem);
    if (busyBlocks.length > MAX_BUSY_BLOCKS_PER_PERSON) {
      this.logger.debug({
        userProfileId: input.userProfileId,
        mailbox: input.mailbox,
        scheduleId: email,
        msg: 'check_availability busy blocks truncated',
      });
      input.notes.push(
        `${email}: busy blocks truncated to ${MAX_BUSY_BLOCKS_PER_PERSON}. Narrow the date range.`,
      );
    }
    if (items.length > MAX_ITEMS_PER_PERSON) {
      this.logger.debug({
        userProfileId: input.userProfileId,
        mailbox: input.mailbox,
        scheduleId: email,
        msg: 'check_availability schedule items truncated',
      });
      input.notes.push(
        `${email}: schedule items truncated to ${MAX_ITEMS_PER_PERSON}. Narrow the date range.`,
      );
    }
    return {
      email,
      busyBlocks: busyBlocks.slice(0, MAX_BUSY_BLOCKS_PER_PERSON),
      items: items.slice(0, MAX_ITEMS_PER_PERSON),
      workingHours: mapGraphWorkingHoursToWorkingHours(input.item.workingHours),
    };
  }
}

function uniqueSchedules(attendees: string[]): string[] {
  const seen = new Set<string>();
  const schedules: string[] = [];
  for (const attendee of attendees) {
    const trimmed = attendee.trim();
    const key = trimmed.toLowerCase();
    if (!SmtpAddressSchema.safeParse(trimmed).success || seen.has(key)) {
      continue;
    }
    seen.add(key);
    schedules.push(trimmed);
  }
  return schedules;
}

function isTooManyEntries(error: GraphScheduleInformation['error']): boolean {
  if (error === undefined || error === null) {
    return false;
  }
  return error.responseCode === '5006' || /too many calendar entries/i.test(error.message ?? '');
}
