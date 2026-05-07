import z from 'zod/v4';

export const DiscoverDelegatedAccessEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.delegated-access.discover'),
  payload: z.object({}),
});
