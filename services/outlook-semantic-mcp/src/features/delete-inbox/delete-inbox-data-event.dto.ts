import z from 'zod/v4';

export const DeleteInboxDataEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.delete-inbox-data.execute'),
  payload: z.object({ userProfileId: z.string() }),
});
