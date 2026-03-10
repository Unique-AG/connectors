import { z } from 'zod/v4';

const regexPattern = z.string().transform((pattern, ctx) => {
  try {
    return new RegExp(pattern);
  } catch {
    ctx.addIssue({ code: 'custom', message: `Invalid regex pattern: ${pattern}` });
    return z.NEVER;
  }
});

export const inboxConfigurationMailFilters = z.object({
  ignoredBefore: z.coerce.date(),
  ignoredSenders: z.array(regexPattern).optional().default([]),
  ignoredContents: z.array(regexPattern).optional().default([]),
});

export type InboxConfigurationMailFilters = z.infer<typeof inboxConfigurationMailFilters>;
