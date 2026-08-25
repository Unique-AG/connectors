import { describe, expect, it } from 'vitest';
import { SmtpAddressSchema, uniqueSmtpAddresses } from '../smtp-address.schema';

describe('SmtpAddressSchema', () => {
  it.each([
    'me@example.com',
    'first.last@example.com',
    'a+tag@example.com',
    "o'brien@example.com",
    'a_b-c@sub.example.co.uk',
    'shared.mailbox@contoso.onmicrosoft.com',
  ])('accepts the real Exchange address %s', (address) => {
    expect(SmtpAddressSchema.parse(address)).toBe(address);
  });

  // These values are interpolated into Graph URL paths, so anything that could escape a path
  // segment has to be rejected before it reaches calendar-graph-path.ts.
  it.each([
    'evil/calendar',
    'me@example.com/calendars',
    'a?b@example.com',
    'a#b@example.com',
    '..%2f@example.com',
    'a b@example.com',
    '',
  ])('rejects %s', (address) => {
    expect(SmtpAddressSchema.safeParse(address).success).toBe(false);
  });
});

describe(uniqueSmtpAddresses.name, () => {
  it('dedupes case-insensitively, trims, and preserves order', () => {
    expect(uniqueSmtpAddresses([' B@x.com ', 'a@x.com', 'b@x.com'])).toEqual([
      'B@x.com',
      'a@x.com',
    ]);
  });

  it('drops entries that are not addresses rather than failing the whole call', () => {
    expect(uniqueSmtpAddresses(['a@x.com', 'nonsense', 'evil/path'])).toEqual(['a@x.com']);
  });
});
