import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { InboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { shouldSkipEmail } from './should-skip-email';

vi.mock('~/features/tracing.utils', () => ({ traceEvent: vi.fn() }));

const FIXED_NOW = new Date('2025-06-15T14:32:00.000Z');

// Recent date well within any 30-day retention window used in these tests.
const RECENT = '2025-06-14T10:00:00.000Z';
// 60 days before FIXED_NOW — outside a 30-day retention window.
const OLD = '2025-04-16T10:00:00.000Z';

const baseFilters = (): InboxConfigurationMailFilters => ({
  retentionWindowInDays: 30,
  ignoredSenders: [],
  ignoredContents: [],
});

const context = { userProfileId: 'user-1' };

describe('shouldSkipEmail', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('no filters match', () => {
    it('returns { skip: false } when no patterns are configured', () => {
      const result = shouldSkipEmail(
        {
          receivedDateTime: RECENT,
          subject: 'Hello',
          from: { emailAddress: { address: 'a@b.com' } },
        },
        baseFilters(),
        context,
      );
      expect(result).toEqual({ skip: false });
    });
  });

  describe('retentionWindowInDays', () => {
    it('skips when receivedDateTime is older than the retention window', () => {
      const result = shouldSkipEmail({ receivedDateTime: OLD }, baseFilters(), context);
      expect(result).toEqual({ skip: true, reason: 'receivedDateTime' });
    });

    it('does not skip when receivedDateTime is within the retention window', () => {
      const result = shouldSkipEmail({ receivedDateTime: RECENT }, baseFilters(), context);
      expect(result).toEqual({ skip: false });
    });
  });

  describe('ignoredSenders', () => {
    it('skips on exact match against sender address', () => {
      const filters = baseFilters();
      filters.ignoredSenders = [/^noreply@example\.com$/];
      const result = shouldSkipEmail(
        { receivedDateTime: RECENT, from: { emailAddress: { address: 'noreply@example.com' } } },
        filters,
        context,
      );
      expect(result).toEqual({
        skip: true,
        reason: 'ignoredSenders',
        matchedPattern: '/^noreply@example\\.com$/',
      });
    });

    it('skips on partial regex match against sender address', () => {
      const filters = baseFilters();
      filters.ignoredSenders = [/no-?reply/i];
      const result = shouldSkipEmail(
        { receivedDateTime: RECENT, from: { emailAddress: { address: 'NoReply@corp.com' } } },
        filters,
        context,
      );
      expect(result).toEqual({
        skip: true,
        reason: 'ignoredSenders',
        matchedPattern: '/no-?reply/i',
      });
    });

    it('does not skip when sender does not match', () => {
      const filters = baseFilters();
      filters.ignoredSenders = [/noreply/];
      const result = shouldSkipEmail(
        { receivedDateTime: RECENT, from: { emailAddress: { address: 'alice@corp.com' } } },
        filters,
        context,
      );
      expect(result).toEqual({ skip: false });
    });

    it('does not skip when sender address is absent', () => {
      const filters = baseFilters();
      filters.ignoredSenders = [/noreply/];
      const result = shouldSkipEmail({ receivedDateTime: RECENT, from: null }, filters, context);
      expect(result).toEqual({ skip: false });
    });
  });

  describe('ignoredContents', () => {
    it('skips when pattern matches subject', () => {
      const filters = baseFilters();
      filters.ignoredContents = [/unsubscribe/i];
      const result = shouldSkipEmail(
        { receivedDateTime: RECENT, subject: 'Click here to Unsubscribe' },
        filters,
        context,
      );
      expect(result).toEqual({
        skip: true,
        reason: 'ignoredContents',
        matchedPattern: '/unsubscribe/i',
      });
    });

    it('skips when pattern matches uniqueBody.content', () => {
      const filters = baseFilters();
      filters.ignoredContents = [/newsletter/i];
      const result = shouldSkipEmail(
        {
          receivedDateTime: RECENT,
          subject: 'Weekly update',
          uniqueBody: { content: 'You are receiving this Newsletter' },
        },
        filters,
        context,
      );
      expect(result).toEqual({
        skip: true,
        reason: 'ignoredContents',
        matchedPattern: '/newsletter/i',
      });
    });

    it('does not skip when pattern matches neither subject nor body', () => {
      const filters = baseFilters();
      filters.ignoredContents = [/unsubscribe/i];
      const result = shouldSkipEmail(
        {
          receivedDateTime: RECENT,
          subject: 'Project update',
          uniqueBody: { content: 'See attached.' },
        },
        filters,
        context,
      );
      expect(result).toEqual({ skip: false });
    });

    it('does not skip when uniqueBody is null', () => {
      const filters = baseFilters();
      filters.ignoredContents = [/newsletter/i];
      const result = shouldSkipEmail(
        { receivedDateTime: RECENT, subject: 'Hello', uniqueBody: null },
        filters,
        context,
      );
      expect(result).toEqual({ skip: false });
    });
  });

  describe('short-circuit', () => {
    it('returns on first match and does not evaluate later filters', () => {
      const contentsPattern = {
        test: vi.fn().mockReturnValue(false),
        source: 'anything',
      } as unknown as RegExp;

      const filters = baseFilters();
      filters.ignoredSenders = [/noreply/];
      filters.ignoredContents = [contentsPattern];

      const result = shouldSkipEmail(
        { receivedDateTime: RECENT, from: { emailAddress: { address: 'noreply@example.com' } } },
        filters,
        context,
      );

      expect(result).toEqual({ skip: true, reason: 'ignoredSenders', matchedPattern: '/noreply/' });
      expect(contentsPattern.test).not.toHaveBeenCalled();
    });
  });

  describe('error handling', () => {
    it('returns { skip: false } and emits traceEvent with userProfileId when a filter throws', async () => {
      const { traceEvent } = await import('~/features/tracing.utils');
      const throwingPattern = {
        test: () => {
          throw new Error('regex engine failure');
        },
        source: 'bad',
        toString: () => '/bad/',
      } as unknown as RegExp;

      const filters = baseFilters();
      filters.ignoredSenders = [throwingPattern];

      const result = shouldSkipEmail(
        { receivedDateTime: RECENT, from: { emailAddress: { address: 'a@b.com' } } },
        filters,
        context,
      );

      expect(result).toEqual({ skip: false });
      expect(traceEvent).toHaveBeenCalledWith('shouldSkipEmail.error', {
        userProfileId: context.userProfileId,
      });
    });
  });
});
