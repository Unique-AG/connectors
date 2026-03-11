import z from 'zod/v4';

export const FullSyncRecoveryEventDto = z.object({
  userProfileId: z.string(),
});
