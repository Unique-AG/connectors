import z from 'zod/v4';

export const FolderMovementSyncEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.sync.folder-movement'),
  payload: z.object({ userProfileId: z.string() }),
});
