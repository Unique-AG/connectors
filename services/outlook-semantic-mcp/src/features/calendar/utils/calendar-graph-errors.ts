import { GraphError } from '@microsoft/microsoft-graph-client';

export class CalendarConsentRequiredError extends Error {
  public constructor() {
    super(
      'Calendar access requires re-authorization. Reconnect your Outlook account so Microsoft can grant Calendars.ReadWrite.Shared.',
    );
    this.name = 'CalendarConsentRequiredError';
  }
}

export function isCalendarPermissionDeniedError(error: unknown): boolean {
  return error instanceof GraphError && (error.statusCode === 401 || error.statusCode === 403);
}

export function isGraphBadRequestError(error: unknown): boolean {
  return error instanceof GraphError && error.statusCode === 400;
}

export function isGraphNotFoundError(error: unknown): boolean {
  return error instanceof GraphError && error.statusCode === 404;
}

export function isGetScheduleTooManyEntriesError(error: unknown): boolean {
  if (!(error instanceof GraphError)) {
    return false;
  }
  return error.code === '5006' || /too many calendar entries/i.test(error.message);
}
