import { describe, expect, it, vi } from 'vitest';
import { shouldSkipEmail } from './should-skip-email';
import type { InboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';

const baseFilters = (): InboxConfigurationMailFilters => ({
  dateFrom: new Date('2020-01-01T00:00:00Z'),
  ignoredSenders: [],
  ignoredContents: [],
});

const context = { userProfileId: 'user-1' };

describe('shouldSkipEmail', () => {
  describe('no filters match', () => {
    it('returns { skip: false } when no patterns are configured', () => {
      const result = shouldSkipEmail({ subject: 'Hello', from: { emailAddress: { address: 'a@b.com' } } }, baseFilters(), context);
      expect(result).toEqual({ skip: false });
    });
  });

  describe('dateFrom', () => {
    it('skips when createdDateTime is before dateFrom', () => {
      const result = shouldSkipEmail(
        { createdDateTime: '2019-06-01T00:00:00Z' },
        baseFilters(),
        context,
      );
      expect(result).toEqual({ skip: true, reason: 'dateFrom' });
    });

    it('does not skip when createdDateTime is after dateFrom', () => {
      const result = shouldSkipEmail(
        { createdDateTime: '2021-01-01T00:00:00Z' },
        baseFilters(),
        context,
      );
      expect(result).toEqual({ skip: false });
    });

    it('does not skip when createdDateTime is absent', () => {
      const result = shouldSkipEmail({}, baseFilters(), context);
      expect(result).toEqual({ skip: false });
    });
  });

  describe('ignoredSenders', () => {
    it('skips on exact match against sender address', () => {
      const filters = baseFilters();
      filters.ignoredSenders = [/^noreply@example\.com$/];
      const result = shouldSkipEmail(
        { from: { emailAddress: { address: 'noreply@example.com' } } },
        filters,
        context,
      );
      expect(result).toEqual({ skip: true, reason: 'ignoredSenders', matchedPattern: '^noreply@example\\.com$' });
    });

    it('skips on partial regex match against sender address', () => {
      const filters = baseFilters();
      filters.ignoredSenders = [/no-?reply/i];
      const result = shouldSkipEmail(
        { from: { emailAddress: { address: 'NoReply@corp.com' } } },
        filters,
        context,
      );
      expect(result).toEqual({ skip: true, reason: 'ignoredSenders', matchedPattern: 'no-?reply' });
    });

    it('does not skip when sender does not match', () => {
      const filters = baseFilters();
      filters.ignoredSenders = [/noreply/];
      const result = shouldSkipEmail(
        { from: { emailAddress: { address: 'alice@corp.com' } } },
        filters,
        context,
      );
      expect(result).toEqual({ skip: false });
    });

    it('does not skip when sender address is absent', () => {
      const filters = baseFilters();
      filters.ignoredSenders = [/noreply/];
      const result = shouldSkipEmail({ from: null }, filters, context);
      expect(result).toEqual({ skip: false });
    });
  });

  describe('ignoredContents', () => {
    it('skips when pattern matches subject', () => {
      const filters = baseFilters();
      filters.ignoredContents = [/unsubscribe/i];
      const result = shouldSkipEmail({ subject: 'Click here to Unsubscribe' }, filters, context);
      expect(result).toEqual({ skip: true, reason: 'ignoredContents', matchedPattern: 'unsubscribe' });
    });

    it('skips when pattern matches uniqueBody.content', () => {
      const filters = baseFilters();
      filters.ignoredContents = [/newsletter/i];
      const result = shouldSkipEmail(
        { subject: 'Weekly update', uniqueBody: { content: 'You are receiving this Newsletter' } },
        filters,
        context,
      );
      expect(result).toEqual({ skip: true, reason: 'ignoredContents', matchedPattern: 'newsletter' });
    });

    it('does not skip when pattern matches neither subject nor body', () => {
      const filters = baseFilters();
      filters.ignoredContents = [/unsubscribe/i];
      const result = shouldSkipEmail(
        { subject: 'Project update', uniqueBody: { content: 'See attached.' } },
        filters,
        context,
      );
      expect(result).toEqual({ skip: false });
    });
  });

  describe('short-circuit', () => {
    it('returns on first match and does not evaluate later filters', () => {
      const contentsPattern = { test: vi.fn().mockReturnValue(false), source: 'anything' } as unknown as RegExp;

      const filters = baseFilters();
      filters.ignoredSenders = [/noreply/];
      filters.ignoredContents = [contentsPattern];

      const result = shouldSkipEmail(
        { from: { emailAddress: { address: 'noreply@example.com' } } },
        filters,
        context,
      );

      expect(result).toEqual({ skip: true, reason: 'ignoredSenders', matchedPattern: 'noreply' });
      expect(contentsPattern.test).not.toHaveBeenCalled();
    });
  });

  describe('error handling', () => {
    it('returns { skip: false } and fails open when a filter throws', () => {
      const throwingPattern = {
        test: () => { throw new Error('regex engine failure'); },
        source: 'bad',
      } as unknown as RegExp;

      const filters = baseFilters();
      filters.ignoredSenders = [throwingPattern];

      const result = shouldSkipEmail(
        { from: { emailAddress: { address: 'a@b.com' } } },
        filters,
        context,
      );

      expect(result).toEqual({ skip: false });
    });
  });
});
