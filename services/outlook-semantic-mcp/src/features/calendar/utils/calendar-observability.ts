import { GraphError } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
} from './calendar-graph-errors';

export type CalendarRecoveredOutcome =
  | 'consent'
  | 'not_found'
  | 'permission'
  | 'invalid'
  | 'too_many_entries'
  | 'delegated_skipped';

export function calendarUserProfileId(userProfileId: UserProfileTypeID | string): string {
  return userProfileId.toString();
}

export function calendarTraceAttrs(attrs: {
  userProfileId: string;
  mailbox?: string;
  calendarId?: string;
  operation?: string;
}): void {
  traceAttrs({
    userProfileId: attrs.userProfileId,
    ...(attrs.mailbox !== undefined ? { mailbox: attrs.mailbox } : {}),
    ...(attrs.calendarId !== undefined ? { calendarId: attrs.calendarId } : {}),
    ...(attrs.operation !== undefined ? { operation: attrs.operation } : {}),
  });
}

export function logCalendarRecovered(
  logger: Logger,
  input: {
    userProfileId: string;
    msg: string;
    outcome: CalendarRecoveredOutcome;
    mailbox?: string;
    calendarId?: string;
    ownerEmail?: string;
    err?: unknown;
  },
): void {
  logger.warn({
    userProfileId: input.userProfileId,
    msg: input.msg,
    ...(input.mailbox !== undefined ? { mailbox: input.mailbox } : {}),
    ...(input.calendarId !== undefined ? { calendarId: input.calendarId } : {}),
    ...(input.ownerEmail !== undefined ? { ownerEmail: input.ownerEmail } : {}),
    ...(input.err !== undefined ? { err: input.err } : {}),
  });
  traceEvent('calendar.recovered', {
    outcome: input.outcome,
    ...(input.mailbox !== undefined ? { mailbox: input.mailbox } : {}),
    ...(input.calendarId !== undefined ? { calendarId: input.calendarId } : {}),
    ...(input.ownerEmail !== undefined ? { ownerEmail: input.ownerEmail } : {}),
  });
}

export function classifyCalendarGraphError(input: {
  error: unknown;
  mailbox: string;
  callerEmail: string;
  notFoundMessage?: string;
  invalidMessage?: string;
  deniedDelegatedMessage: string;
}):
  | {
      outcome: Exclude<CalendarRecoveredOutcome, 'delegated_skipped' | 'too_many_entries'>;
      message: string;
      consentRequired?: true;
    }
  | undefined {
  if (input.error instanceof GraphError && input.error.statusCode === 404) {
    if (input.notFoundMessage === undefined) {
      return undefined;
    }
    return { outcome: 'not_found', message: input.notFoundMessage };
  }
  if (input.error instanceof GraphError && input.error.statusCode === 400) {
    if (input.invalidMessage === undefined) {
      return undefined;
    }
    return { outcome: 'invalid', message: input.invalidMessage };
  }
  if (!isCalendarPermissionDeniedError(input.error)) {
    return undefined;
  }
  if (input.mailbox.toLowerCase() === input.callerEmail.toLowerCase()) {
    return {
      outcome: 'consent',
      message: new CalendarConsentRequiredError().message,
      consentRequired: true,
    };
  }
  return { outcome: 'permission', message: input.deniedDelegatedMessage };
}
