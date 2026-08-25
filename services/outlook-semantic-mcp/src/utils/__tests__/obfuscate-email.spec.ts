import { describe, expect, it } from 'vitest';
import { obfuscateEmail } from '../obfuscate-email';

describe(obfuscateEmail.name, () => {
  it('hides the local part and keeps the domain', () => {
    const result = obfuscateEmail('nicolae.bacila@unique.ai');

    expect(result).not.toContain('nicolae');
    expect(result).toMatch(/^[0-9a-f]{12}@unique\.ai$/);
  });

  it('is stable so the same person correlates across log lines', () => {
    expect(obfuscateEmail('a@x.com')).toBe(obfuscateEmail('  A@x.com '));
  });

  it('distinguishes different people on the same domain', () => {
    expect(obfuscateEmail('a@x.com')).not.toBe(obfuscateEmail('b@x.com'));
  });

  it('distinguishes the same local part across tenants', () => {
    expect(obfuscateEmail('admin@dogfood.industries')).not.toBe(obfuscateEmail('admin@unique.ai'));
  });

  it('hashes a value that is not an address at all', () => {
    expect(obfuscateEmail('unknown')).toMatch(/^[0-9a-f]{12}$/);
  });

  it('passes through nullish and empty so optional log fields stay omitted', () => {
    expect(obfuscateEmail(undefined)).toBeUndefined();
    expect(obfuscateEmail(null)).toBeUndefined();
    expect(obfuscateEmail('   ')).toBeUndefined();
  });
});
