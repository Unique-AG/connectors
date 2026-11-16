import * as z from 'zod';

/** Tool-call limit per key. The count is held in each process. */
export const mcpRateLimitConfigSchema = z.object({
  toolCallsPerWindow: z.coerce
    .number<string | undefined>()
    .int()
    .min(1)
    .default(60)
    .describe('Tool calls one key may make within the window.'),
  windowSeconds: z.coerce
    .number<string | undefined>()
    .positive()
    .default(60)
    .describe('Length of the sliding window, in seconds.'),
});

export type McpRateLimitConfig = z.infer<typeof mcpRateLimitConfigSchema>;
