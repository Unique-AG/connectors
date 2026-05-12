import z from 'zod/v4';

export const SyncDelegatedAccessEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.delegated-access.sync'),
  payload: z.object({}),
});
