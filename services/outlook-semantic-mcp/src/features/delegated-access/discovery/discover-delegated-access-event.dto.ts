import z from 'zod/v4';

export const DiscoverDelegatedAccessEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.delegated-access.discover'),
  payload: z.object({
    // Set by the scheduled scan: a new cycle that rechecks every delegate, requested at this time
    // (epoch ms). Without it, a run only processes the delegates the current cycle has not
    // discovered yet.
    newCycleRequestedAt: z.number().optional(),
  }),
});
