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
    ...(attrs.mailbox !== undefined ? { mailbox: obfuscateEmail(attrs.mailbox) } : {}),
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
    ...(input.mailbox !== undefined ? { mailbox: obfuscateEmail(input.mailbox) } : {}),
    ...(input.calendarId !== undefined ? { calendarId: input.calendarId } : {}),
    ...(input.ownerEmail !== undefined ? { ownerEmail: obfuscateEmail(input.ownerEmail) } : {}),
    ...(input.err !== undefined ? { err: input.err } : {}),
  });
  traceEvent('calendar.recovered', {
    outcome: input.outcome,
    ...(input.mailbox !== undefined ? { mailbox: obfuscateEmail(input.mailbox) } : {}),
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
  mailbox: string;
  callerEmail: string;
  calendarId?: string;
  operation: string;
  notFoundMessage?: string;
  invalidMessage?: string;
  deniedDelegatedMessage: string;
}): CalendarGraphRecoveredFailure {
  const classified = classifyCalendarGraphError({
    error: input.error,
    mailbox: input.mailbox,
    callerEmail: input.callerEmail,
    notFoundMessage: input.notFoundMessage,
    invalidMessage: input.invalidMessage,
    deniedDelegatedMessage: input.deniedDelegatedMessage,
  });
  if (classified.outcome === 'unhandled') {
    throw input.error;
  }
  logCalendarRecovered(input.logger, {
    userProfileId: input.userProfileId,
    mailbox: input.mailbox,
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
  mailbox: string;
  callerEmail: string;
  notFoundMessage?: string;
  invalidMessage?: string;
  deniedDelegatedMessage: string;
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
  if (input.mailbox.toLowerCase() === input.callerEmail.toLowerCase()) {
    return {
      outcome: 'consent',
      message: new CalendarConsentRequiredError().message,
      consentRequired: true,
    };
  }
  return { outcome: 'permission', message: input.deniedDelegatedMessage };
}
