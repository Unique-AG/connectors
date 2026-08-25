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
} from '~/utils/relative-range';
import { resolveIanaTimezone } from '~/utils/resolve-iana-timezone';
import {
  GraphGetScheduleResponseSchema,
  type GraphScheduleInformation,
  type GraphScheduleItem,
} from './calendar.schemas';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
  isGetScheduleTooManyEntriesError,
} from './utils/calendar-graph-errors';
import { getSchedulePath, isSmtpAddress } from './utils/calendar-graph-path';
import { type AvailabilityBlock, decodeAvailabilityView } from './utils/decode-availability-view';
import { toGraphDateTimeTimeZone } from './utils/to-graph-date-time-time-zone';

const UTC = 'UTC';
const MAX_SCHEDULES = 20;
const MAX_WINDOW_DAYS = 62;
const DEFAULT_INTERVAL_MINUTES = 30;
const MAX_BUSY_BLOCKS_PER_PERSON = 100;
const MAX_ITEMS_PER_PERSON = 100;
const TOO_MANY_ENTRIES_MESSAGE =
  'This window has more than 1000 calendar entries in a slot. Narrow the date range and try again.';

interface ScheduleItem {
  status: string | null;
  subject: string | null;
  location: string | null;
  isPrivate: boolean;
  start: { dateTime: string; timeZone: string | null };
  end: { dateTime: string; timeZone: string | null };
}

interface WorkingHours {
  daysOfWeek: string[];
  startTime: string | null;
  endTime: string | null;
  timeZone: string | null;
}

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
    private readonly getMailboxTimezoneQuery: GetMailboxTimezoneQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: CheckAvailabilityQueryInput,
  ): Promise<CheckAvailabilityQueryOutput> {
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
    const resolvedWindow = resolveQueryWindow({
      range: input.range,
      startDateTime: input.startDateTime,
      endDateTime: input.endDateTime,
      now: clock,
    });
    const schedules = uniqueSchedules(input.attendees);
    if (schedules.length === 0) {
      return {
        success: false,
        message: 'At least one attendee SMTP address is required.',
        resolvedWindow,
      };
    }
    if (schedules.length > MAX_SCHEDULES) {
      return {
        success: false,
        message: `At most ${MAX_SCHEDULES} addresses can be checked at once. Narrow the attendee list.`,
        resolvedWindow,
      };
    }
    if (isWindowTooLong(resolvedWindow)) {
      return {
        success: false,
        message: `Availability can only be checked for a window shorter than ${MAX_WINDOW_DAYS} days. Use a narrower relative range (today, thisWeek, next7Days) or a shorter absolute window.`,
        availabilityNotes: notes.length > 0 ? notes : undefined,
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
    const intervalMinutes = input.intervalMinutes ?? DEFAULT_INTERVAL_MINUTES;
    const client = this.graphClientFactory.createClientForUser(userProfile.id);

    try {
      const raw = await client
        .api(getSchedulePath(mailbox))
        .header('Prefer', `outlook.timezone="${outlookTimeZone}"`)
        .post({
          schedules,
          startTime: toGraphDateTimeTimeZone({
            iso: resolvedWindow.startDateTime,
            ianaTimeZone,
            windowsTimeZone: outlookTimeZone,
          }),
          endTime: toGraphDateTimeTimeZone({
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
        this.toPersonAvailability({ item, viewStart, intervalMinutes, notes }),
      );
      this.logger.log({
        msg: 'check_availability getSchedule',
        scheduleCount: schedules.length,
        returned: people.length,
      });
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
        return {
          success: false,
          message: TOO_MANY_ENTRIES_MESSAGE,
          availabilityNotes: notes.length > 0 ? notes : undefined,
          resolvedWindow,
        };
      }
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
  }): PersonAvailability {
    const email = input.item.scheduleId ?? 'unknown';
    if (isTooManyEntries(input.item.error)) {
      input.notes.push(`${email}: ${TOO_MANY_ENTRIES_MESSAGE}`);
    } else if (input.item.error?.message !== undefined) {
      input.notes.push(`${email}: ${input.item.error.message}`);
    }
    const busyBlocks = decodeAvailabilityView({
      availabilityView: input.item.availabilityView ?? '',
      start: input.viewStart,
      intervalMinutes: input.intervalMinutes,
    });
    const items = (input.item.scheduleItems ?? []).map(toScheduleItem);
    if (busyBlocks.length > MAX_BUSY_BLOCKS_PER_PERSON) {
      input.notes.push(
        `${email}: busy blocks truncated to ${MAX_BUSY_BLOCKS_PER_PERSON}. Narrow the date range.`,
      );
    }
    if (items.length > MAX_ITEMS_PER_PERSON) {
      input.notes.push(
        `${email}: schedule items truncated to ${MAX_ITEMS_PER_PERSON}. Narrow the date range.`,
      );
    }
    return {
      email,
      busyBlocks: busyBlocks.slice(0, MAX_BUSY_BLOCKS_PER_PERSON),
      items: items.slice(0, MAX_ITEMS_PER_PERSON),
      workingHours: toWorkingHours(input.item),
    };
  }
}

function uniqueSchedules(attendees: string[]): string[] {
  const seen = new Set<string>();
  const schedules: string[] = [];
  for (const attendee of attendees) {
    const trimmed = attendee.trim();
    const key = trimmed.toLowerCase();
    if (!isSmtpAddress(trimmed) || seen.has(key)) {
      continue;
    }
    seen.add(key);
    schedules.push(trimmed);
  }
  return schedules;
}

function isWindowTooLong(window: ResolvedWindow): boolean {
  const duration = Temporal.Instant.from(window.startDateTime).until(
    Temporal.Instant.from(window.endDateTime),
  );
  return Temporal.Duration.compare(duration, { days: MAX_WINDOW_DAYS }) >= 0;
}

function isTooManyEntries(error: GraphScheduleInformation['error']): boolean {
  if (error === undefined || error === null) {
    return false;
  }
  return error.responseCode === '5006' || /too many calendar entries/i.test(error.message ?? '');
}

function toScheduleItem(item: GraphScheduleItem): ScheduleItem {
  const isPrivate = item.isPrivate === true;
  return {
    status: item.status ?? null,
    subject: isPrivate ? null : (item.subject ?? null),
    location: isPrivate ? null : (item.location ?? null),
    isPrivate,
    start: {
      dateTime: item.start?.dateTime ?? '',
      timeZone: item.start?.timeZone ?? null,
    },
    end: {
      dateTime: item.end?.dateTime ?? '',
      timeZone: item.end?.timeZone ?? null,
    },
  };
}

function toWorkingHours(item: GraphScheduleInformation): WorkingHours | null {
  const hours = item.workingHours;
  if (hours === undefined || hours === null) {
    return null;
  }
  return {
    daysOfWeek: hours.daysOfWeek ?? [],
    startTime: hours.startTime ?? null,
    endTime: hours.endTime ?? null,
    timeZone: hours.timeZone?.name ?? null,
  };
}
