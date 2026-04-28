import z from 'zod/v4';

export const VerifyDelegatedAccessEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.delegated-access.verify'),
  payload: z.object({ pipelineId: z.string() }),
});
