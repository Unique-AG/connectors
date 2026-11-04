import * as z from 'zod';

/**
 * How many tool calls one key may make within a sliding window. Register it under the
 * `mcpRateLimit` namespace to read `MCP_RATE_LIMIT_TOOL_CALLS_PER_WINDOW` and
 * `MCP_RATE_LIMIT_WINDOW_SECONDS`. The count is held in each process, so with several replicas a
 * key can make that many calls on each of them.
 */
export const mcpRateLimitConfigSchema = z.object({
  toolCallsPerWindow: z.coerce
    .number()
    .int()
    .min(1)
    .prefault(60)
    .describe('Tool calls one key may make within the window.'),
  windowSeconds: z.coerce
    .number()
    .positive()
    .prefault(60)
    .describe('Length of the sliding window, in seconds.'),
});

export type McpRateLimitConfig = z.infer<typeof mcpRateLimitConfigSchema>;
