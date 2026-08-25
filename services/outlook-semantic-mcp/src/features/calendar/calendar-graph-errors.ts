import { GraphError } from '@microsoft/microsoft-graph-client';

export class CalendarConsentRequiredError extends Error {
  public constructor() {
    super(
      'Calendar access requires re-authorization. Reconnect your Outlook account so Microsoft can grant Calendars.ReadWrite.Shared.',
    );
    this.name = 'CalendarConsentRequiredError';
  }
}

export function isInsufficientCalendarScopeError(error: unknown): boolean {
  if (!(error instanceof GraphError)) {
    return false;
  }
  if (error.statusCode !== 401 && error.statusCode !== 403) {
    return false;
  }
  const code = (error.code ?? '').toLowerCase();
  const message = (error.message ?? '').toLowerCase();
  return (
    code.includes('accessdenied') ||
    code.includes('authorization_requestdenied') ||
    message.includes('scope') ||
    message.includes('consent')
  );
}
