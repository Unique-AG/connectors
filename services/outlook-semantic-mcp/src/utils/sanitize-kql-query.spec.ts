import { describe, expect, it } from 'vitest';
import { sanitizeKqlQuery } from './sanitize-kql-query';

describe('sanitizeKqlQuery', () => {
  describe('smart quote normalization', () => {
    it('replaces Unicode left/right single quotes (‘’) with ASCII apostrophes and quotes the clause', () => {
      expect(sanitizeKqlQuery('subject:‘hello world’')).toBe('"subject:\\"hello world\\""');
    });

    it('replaces Unicode left/right double quotes (“”) with ASCII double quotes and quotes the clause', () => {
      expect(sanitizeKqlQuery('subject:“hello world”')).toBe('"subject:\\"hello world\\""');
    });
  });

  describe('boolean operator uppercasing', () => {
    it('uppercases lowercase and and drops it (space is implicit AND)', () => {
      expect(sanitizeKqlQuery('from:alice@example.com and subject:report')).toBe(
        '"from:alice@example.com subject:report"',
      );
    });

    it('uppercases lowercase or and keeps it explicit', () => {
      expect(sanitizeKqlQuery('from:alice@example.com or from:bob@example.com')).toBe(
        '"from:alice@example.com OR from:bob@example.com"',
      );
    });

    it('uppercases lowercase not and keeps it explicit', () => {
      expect(sanitizeKqlQuery('subject:report not from:alice@example.com')).toBe(
        '"subject:report NOT from:alice@example.com"',
      );
    });

    it('drops already-uppercase AND (space is implicit AND)', () => {
      expect(sanitizeKqlQuery('from:alice@example.com AND subject:report')).toBe(
        '"from:alice@example.com subject:report"',
      );
    });

    it('does not uppercase operator letters inside words', () => {
      expect(sanitizeKqlQuery('from:anderson@example.com')).toBe('"from:anderson@example.com"');
      expect(sanitizeKqlQuery('subject:notable')).toBe('"subject:notable"');
    });

    it('does not uppercase boolean keywords inside double-quoted phrases', () => {
      expect(sanitizeKqlQuery('subject:"budget and planning"')).toBe(
        '"subject:\\"budget and planning\\""',
      );
      expect(sanitizeKqlQuery('body:"risk or return"')).toBe('"body:\\"risk or return\\""');
      expect(sanitizeKqlQuery('subject:"do not reply" AND from:alice@example.com')).toBe(
        '"subject:\\"do not reply\\" from:alice@example.com"',
      );
    });
  });

  describe('date clamping', () => {
    it('clamps invalid received date (Feb 30) to last valid day', () => {
      expect(sanitizeKqlQuery('received>=2026-02-30')).toBe('"received>=2026-02-28"');
    });

    it('clamps invalid sent date (Feb 30) to last valid day', () => {
      expect(sanitizeKqlQuery('sent<=2026-02-30')).toBe('"sent<=2026-02-28"');
    });

    it('clamps Apr 31 to Apr 30', () => {
      expect(sanitizeKqlQuery('received>=2024-04-31')).toBe('"received>=2024-04-30"');
    });

    it('passes through valid dates unchanged', () => {
      expect(sanitizeKqlQuery('received>=2024-01-15')).toBe('"received>=2024-01-15"');
      expect(sanitizeKqlQuery('sent<=2024-12-31')).toBe('"sent<=2024-12-31"');
    });

    it('handles all comparison operators', () => {
      expect(sanitizeKqlQuery('received>2026-02-30')).toBe('"received>2026-02-28"');
      expect(sanitizeKqlQuery('received<2026-02-30')).toBe('"received<2026-02-28"');
      expect(sanitizeKqlQuery('received>=2026-02-30')).toBe('"received>=2026-02-28"');
      expect(sanitizeKqlQuery('received<=2026-02-30')).toBe('"received<=2026-02-28"');
    });
  });

  describe('unsupported property stripping', () => {
    it('strips folder: clauses', () => {
      expect(sanitizeKqlQuery('folder:Inbox subject:report')).toBe('"subject:report"');
    });

    it('strips isRead: clauses', () => {
      expect(sanitizeKqlQuery('isRead:true from:alice@example.com')).toBe(
        '"from:alice@example.com"',
      );
    });

    it('strips quoted unsupported property clauses', () => {
      expect(sanitizeKqlQuery('flag:"follow up" subject:report')).toBe('"subject:report"');
    });

    it('strips multiple unsupported properties at once', () => {
      expect(sanitizeKqlQuery('folder:Inbox isRead:true subject:budget')).toBe('"subject:budget"');
    });
  });

  describe('supported properties are preserved', () => {
    it.each([
      ['from:alice@example.com', '"from:alice@example.com"'],
      ['to:bob@example.com', '"to:bob@example.com"'],
      ['cc:carol@example.com', '"cc:carol@example.com"'],
      ['bcc:dave@example.com', '"bcc:dave@example.com"'],
      ['participants:alice@example.com', '"participants:alice@example.com"'],
      ['recipients:bob@example.com', '"recipients:bob@example.com"'],
      ['subject:report', '"subject:report"'],
      ['body:quarterly', '"body:quarterly"'],
      ['attachment:report.pdf', '"attachment:report.pdf"'],
      ['hasAttachment:true', '"hasAttachment:true"'],
      ['hasAttachments:false', '"hasAttachments:false"'],
      ['importance:high', '"importance:high"'],
      ['kind:meetings', '"kind:meetings"'],
      ['size:1..1048576', '"size:1..1048576"'],
      ['category:"Red Category"', '"category:\\"Red Category\\""'],
    ])('quotes %s correctly', (input, expected) => {
      expect(sanitizeKqlQuery(input)).toBe(expected);
    });
  });

  describe('compound queries', () => {
    it('wraps the whole query in a single outer-quoted string with space as implicit AND', () => {
      const query = 'from:alice@example.com subject:"Q2 budget" received>=2024-01-01';
      expect(sanitizeKqlQuery(query)).toBe(
        '"from:alice@example.com subject:\\"Q2 budget\\" received>=2024-01-01"',
      );
    });

    it('strips unsupported filters while keeping supported ones in compound query', () => {
      expect(sanitizeKqlQuery('from:alice@example.com folder:Inbox subject:report')).toBe(
        '"from:alice@example.com subject:report"',
      );
    });

    it('normalises boolean operators in compound query, keeping OR and dropping AND', () => {
      expect(sanitizeKqlQuery('from:hr@acme.com or from:payroll@acme.com and subject:salary')).toBe(
        '"from:hr@acme.com OR from:payroll@acme.com subject:salary"',
      );
    });

    it('returns empty string when all properties are stripped', () => {
      expect(sanitizeKqlQuery('folder:Inbox isRead:true')).toBe('');
    });
  });

  describe('free text queries', () => {
    it('wraps a single free-text word in outer quotes', () => {
      expect(sanitizeKqlQuery('TanStack')).toBe('"TanStack"');
    });

    it('wraps multiple free-text words as a single outer-quoted phrase', () => {
      expect(sanitizeKqlQuery('supply chain attack')).toBe('"supply chain attack"');
    });

    it('keeps OR between free-text terms within the outer-quoted string', () => {
      expect(sanitizeKqlQuery('TanStack OR "Mini Shai-Hulud"')).toBe(
        '"TanStack OR \\"Mini Shai-Hulud\\""',
      );
    });
  });
});
