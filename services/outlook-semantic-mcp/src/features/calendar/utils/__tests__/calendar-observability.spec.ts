import { GraphError } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import {
  classifyCalendarGraphError,
  logCalendarRecovered,
  recoverCalendarGraphError,
} from '../calendar-observability';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
  traceEvent: vi.fn(),
}));

function makeGraphError(statusCode: number): GraphError {
  return new GraphError(statusCode, 'Access denied');
}

describe(classifyCalendarGraphError.name, () => {
  it('maps 404 to not_found when a message is provided', () => {
    expect(
      classifyCalendarGraphError({
        error: makeGraphError(404),
        mailbox: 'me@example.com',
        callerEmail: 'me@example.com',
        notFoundMessage: 'missing',
        deniedDelegatedMessage: 'denied',
      }),
    ).toEqual({ outcome: 'not_found', message: 'missing' });
  });

  it('maps 403 on the caller mailbox to consent', () => {
    expect(
      classifyCalendarGraphError({
        error: makeGraphError(403),
        mailbox: 'me@example.com',
        callerEmail: 'me@example.com',
        deniedDelegatedMessage: 'denied',
      }),
    ).toEqual({
      outcome: 'consent',
      message: expect.stringContaining('re-authorization'),
      consentRequired: true,
    });
  });

  it('maps 403 on a delegated mailbox to permission', () => {
    expect(
      classifyCalendarGraphError({
        error: makeGraphError(403),
        mailbox: 'banker@example.com',
        callerEmail: 'me@example.com',
        deniedDelegatedMessage: 'denied',
      }),
    ).toEqual({ outcome: 'permission', message: 'denied' });
  });

  it('returns undefined for unhandled errors', () => {
    expect(
      classifyCalendarGraphError({
        error: makeGraphError(500),
        mailbox: 'me@example.com',
        callerEmail: 'me@example.com',
        deniedDelegatedMessage: 'denied',
      }),
    ).toBeUndefined();
  });
});

describe(logCalendarRecovered.name, () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('warns with userProfileId and records a recovered span event', async () => {
    const { traceEvent } = await import('~/features/tracing.utils');
    const warn = vi.fn();
    const logger = { warn } as unknown as Logger;

    logCalendarRecovered(logger, {
      userProfileId: 'user_profile_1',
      mailbox: 'me@example.com',
      ownerEmail: 'banker@example.com',
      outcome: 'consent',
      msg: 'list_calendars consent required',
    });

    // The sink de-identifies, so a caller cannot leak an address by forgetting to.
    expect(warn).toHaveBeenCalledWith({
      userProfileId: 'user_profile_1',
      mailbox: obfuscateEmail('me@example.com'),
      ownerEmail: obfuscateEmail('banker@example.com'),
      msg: 'list_calendars consent required',
    });
    expect(traceEvent).toHaveBeenCalledWith('calendar.recovered', {
      outcome: 'consent',
      mailbox: obfuscateEmail('me@example.com'),
      ownerEmail: obfuscateEmail('banker@example.com'),
    });
    expect(JSON.stringify(warn.mock.calls[0])).not.toContain('me@example.com');
  });
});

describe(recoverCalendarGraphError.name, () => {
  it('logs and returns a typed failure with errorType', () => {
    const warn = vi.fn();
    const recovered = recoverCalendarGraphError({
      error: makeGraphError(404),
      logger: { warn } as unknown as Logger,
      userProfileId: 'user_profile_1',
      mailbox: 'me@example.com',
      callerEmail: 'me@example.com',
      calendarId: 'cal-own',
      operation: 'create_event',
      notFoundMessage: 'missing',
      deniedDelegatedMessage: 'denied',
    });

    expect(recovered).toEqual({
      success: false,
      message: 'missing',
      errorType: 'not_found',
    });
    expect(warn).toHaveBeenCalledWith(
      expect.objectContaining({
        userProfileId: 'user_profile_1',
        msg: 'create_event not_found',
      }),
    );
  });

  it('returns undefined for unhandled errors so the caller can rethrow', () => {
    expect(
      recoverCalendarGraphError({
        error: makeGraphError(500),
        logger: { warn: vi.fn() } as unknown as Logger,
        userProfileId: 'user_profile_1',
        mailbox: 'me@example.com',
        callerEmail: 'me@example.com',
        operation: 'create_event',
        deniedDelegatedMessage: 'denied',
      }),
    ).toBeUndefined();
  });
});
