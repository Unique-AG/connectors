import z from 'zod/v4';

export const DiscoverDelegatedAccessEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.delegated-access.discover'),
  payload: z.object({
    // The scheduled scan starts a cycle that rechecks every delegate. Without it, a run only
    // processes the delegates the current cycle has not discovered yet.
    newCycle: z.boolean().default(false),
  }),
});
