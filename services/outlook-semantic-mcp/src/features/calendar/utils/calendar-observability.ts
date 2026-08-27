import { Logger } from '@nestjs/common';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import {
  CalendarConsentRequiredError,
  isCalendarPermissionDeniedError,
  isGraphBadRequestError,
  isGraphNotFoundError,
} from './calendar-graph-errors';

export type CalendarRecoveredOutcome =
  | 'consent'
  | 'not_found'
  | 'invalid'
  | 'too_many_entries'
  | 'delegated_skipped';

export function calendarUserProfileId(userProfileId: UserProfileTypeID | string): string {
  return userProfileId.toString();
}

/**
 * Identity fields for a calendar log line. Obfuscation happens here rather than at the call site,
 * so callers pass the raw signed-in address and no log path can forget to mask it.
 */
export function calendarLogUser(
  userProfileId: string,
  userProfileEmail: string,
): { userProfileId: string; userProfileEmail: string } {
  return { userProfileId, userProfileEmail: obfuscateEmail(userProfileEmail) };
}

export function calendarTraceAttrs(attrs: {
  userProfileId: string;
  userProfileEmail?: string;
  calendarId?: string;
  operation?: string;
}): void {
  traceAttrs({
    userProfileId: attrs.userProfileId,
    ...(attrs.userProfileEmail !== undefined
      ? { userProfileEmail: obfuscateEmail(attrs.userProfileEmail) }
      : {}),
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
    userProfileEmail?: string;
    calendarId?: string;
    ownerEmail?: string;
    err?: unknown;
  },
): void {
  logger.warn({
    userProfileId: input.userProfileId,
    msg: input.msg,
    ...(input.userProfileEmail !== undefined
      ? { userProfileEmail: obfuscateEmail(input.userProfileEmail) }
      : {}),
    ...(input.calendarId !== undefined ? { calendarId: input.calendarId } : {}),
    ...(input.ownerEmail !== undefined ? { ownerEmail: obfuscateEmail(input.ownerEmail) } : {}),
    ...(input.err !== undefined ? { err: input.err } : {}),
  });
  traceEvent('calendar.recovered', {
    outcome: input.outcome,
    ...(input.userProfileEmail !== undefined
      ? { userProfileEmail: obfuscateEmail(input.userProfileEmail) }
      : {}),
    ...(input.calendarId !== undefined ? { calendarId: input.calendarId } : {}),
    ...(input.ownerEmail !== undefined ? { ownerEmail: obfuscateEmail(input.ownerEmail) } : {}),
  });
}

export type CalendarGraphErrorType = Exclude<
  CalendarRecoveredOutcome,
  'delegated_skipped' | 'too_many_entries'
>;

export interface CalendarGraphRecoveredFailure {
  success: false;
  message: string;
  errorType: CalendarGraphErrorType;
  consentRequired?: true;
}

export type CalendarGraphErrorClassification =
  | {
      outcome: CalendarGraphErrorType;
      message: string;
      consentRequired?: true;
    }
  | { outcome: 'unhandled' };

export function recoverCalendarGraphError(input: {
  error: unknown;
  logger: Logger;
  userProfileId: string;
  userProfileEmail: string;
  calendarId?: string;
  operation: string;
  notFoundMessage?: string;
  invalidMessage?: string;
}): CalendarGraphRecoveredFailure {
  const classified = classifyCalendarGraphError({
    error: input.error,
    notFoundMessage: input.notFoundMessage,
    invalidMessage: input.invalidMessage,
  });
  if (classified.outcome === 'unhandled') {
    throw input.error;
  }
  logCalendarRecovered(input.logger, {
    userProfileId: input.userProfileId,
    userProfileEmail: input.userProfileEmail,
    calendarId: input.calendarId,
    outcome: classified.outcome,
    msg: `${input.operation} ${classified.outcome}`,
    err: input.error,
  });
  return {
    success: false,
    message: classified.message,
    errorType: classified.outcome,
    ...(classified.consentRequired === true ? { consentRequired: true } : {}),
  };
}

export function classifyCalendarGraphError(input: {
  error: unknown;
  notFoundMessage?: string;
  invalidMessage?: string;
}): CalendarGraphErrorClassification {
  if (isGraphNotFoundError(input.error)) {
    if (input.notFoundMessage === undefined) {
      return { outcome: 'unhandled' };
    }
    return { outcome: 'not_found', message: input.notFoundMessage };
  }
  if (isGraphBadRequestError(input.error)) {
    if (input.invalidMessage === undefined) {
      return { outcome: 'unhandled' };
    }
    return { outcome: 'invalid', message: input.invalidMessage };
  }
  if (!isCalendarPermissionDeniedError(input.error)) {
    return { outcome: 'unhandled' };
  }
  // Every addressable calendar lives in the caller's own mailbox, so a denial is always consent.
  return {
    outcome: 'consent',
    message: new CalendarConsentRequiredError().message,
    consentRequired: true,
  };
}
