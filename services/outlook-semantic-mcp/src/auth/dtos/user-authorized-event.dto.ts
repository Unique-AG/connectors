import z from 'zod/v4';

export const UserAuthorizedEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.auth.user-authorized'),
  payload: z.object({ userProfileId: z.string() }),
});
