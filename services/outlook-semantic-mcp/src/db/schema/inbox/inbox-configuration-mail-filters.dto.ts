import { isNullish } from 'remeda';
import safeRegex from 'safe-regex2';
import { z } from 'zod/v4';

const regexPattern = z.string().transform((pattern, ctx) => {
  const regexParts = /\/(.*)\/(.*)/.exec(pattern);
  const patternPart = regexParts?.[1];
  const flagsPart = regexParts?.[2];
  if (isNullish(patternPart) || isNullish(flagsPart)) {
    ctx.addIssue({ code: 'custom', message: `Invalid regex pattern: ${pattern}` });
    return z.NEVER;
  }

  try {
    const compiled = new RegExp(patternPart, patternPart);
    if (!safeRegex(compiled)) {
      ctx.addIssue({
        code: 'custom',
        message: `Unsafe regex pattern (potential ReDoS): ${pattern}`,
      });
      return z.NEVER;
    }
    return compiled;
  } catch {
    ctx.addIssue({ code: 'custom', message: `Invalid regex pattern: ${pattern}` });
    return z.NEVER;
  }
});

export const inboxConfigurationMailFilters = z.object({
  retentionWindowInDays: z.number().int().positive(),
  ignoredSenders: z.array(regexPattern).optional().default([]),
  ignoredContents: z.array(regexPattern).optional().default([]),
});

export type InboxConfigurationMailFilters = z.infer<typeof inboxConfigurationMailFilters>;

export function computeIgnoredBefore(days: number): Date {
  const date = new Date();
  date.setDate(date.getDate() - days);
  date.setHours(0, 0, 0, 0);
  return date;
}

export function serializeMailFilters(
  filters: InboxConfigurationMailFilters,
): Record<string, unknown> {
  return {
    retentionWindowInDays: filters.retentionWindowInDays,
    ignoredSenders: filters.ignoredSenders.map((reg) => reg.toString()),
    ignoredContents: filters.ignoredContents.map((reg) => reg.toString()),
  };
}
