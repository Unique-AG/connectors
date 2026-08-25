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
