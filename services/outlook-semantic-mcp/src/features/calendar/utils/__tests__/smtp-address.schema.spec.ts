import { describe, expect, it } from 'vitest';
import { SmtpAddressSchema } from '../smtp-address.schema';

describe('SmtpAddressSchema', () => {
  it('accepts a normal SMTP address and rejects path characters', () => {
    expect(SmtpAddressSchema.parse('me@example.com')).toBe('me@example.com');
    expect(SmtpAddressSchema.safeParse('evil/calendar').success).toBe(false);
    expect(SmtpAddressSchema.safeParse('me@example.com/calendars').success).toBe(false);
  });
});
