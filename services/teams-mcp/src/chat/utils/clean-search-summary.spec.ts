import { describe, expect, it } from 'vitest';
import { cleanSearchSummary } from './clean-search-summary';

describe('cleanSearchSummary', () => {
  it('strips hit-highlighting markup and keeps the matched term', () => {
    expect(cleanSearchSummary('Deploy is <c0>green</c0>.')).toBe('Deploy is green.');
  });

  it('strips several numbered highlight elements', () => {
    expect(cleanSearchSummary('<c0>deploy</c0> to <c1>prod</c1>')).toBe('deploy to prod');
  });

  it('decodes HTML entities', () => {
    expect(cleanSearchSummary('Ann &amp; Bob said &quot;ship it&quot;')).toBe(
      'Ann & Bob said "ship it"',
    );
  });

  it('keeps the leading ellipsis Graph puts on a mid-message snippet', () => {
    expect(cleanSearchSummary('...Test with the TDF account')).toBe('...Test with the TDF account');
  });

  it('collapses runs of spaces left behind by removed markup', () => {
    expect(cleanSearchSummary('Deploy   is  <c0>green</c0>')).toBe('Deploy is green');
  });

  it('preserves newlines inside a multi-line snippet', () => {
    expect(cleanSearchSummary('first line\nsecond line')).toBe('first line\nsecond line');
  });

  it('returns null for a null summary', () => {
    expect(cleanSearchSummary(null)).toBeNull();
  });

  it('returns null for an undefined summary', () => {
    expect(cleanSearchSummary(undefined)).toBeNull();
  });

  it('returns null for a summary that is only markup', () => {
    expect(cleanSearchSummary('<c0></c0>   ')).toBeNull();
  });
});
