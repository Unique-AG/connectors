import z from 'zod/v4';

export const FolderMovementSyncEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.folder-movement.process'),
  payload: z.object({ userProfileId: z.string() }),
});
