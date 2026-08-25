import * as z from 'zod';

export const SmtpAddressSchema = z
  .string()
  .regex(/^[^\s/?#@]+@[^\s/?#@]+$/, 'Must be an SMTP address');

export function smtpAddress(description: string) {
  return SmtpAddressSchema.describe(description);
}
